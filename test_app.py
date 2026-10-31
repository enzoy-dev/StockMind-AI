"""Verificações dos fluxos do dashboard com banco temporário."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import pandas as pd
from streamlit.testing.v1 import AppTest

from app import precisam_revisao
from stockmind.inventory import planejar_estoque


class TestDecisionFiltering(unittest.TestCase):
    def test_compra_futura_por_seguranca_exige_revisao_sem_falta_fisica(self):
        previsao = pd.DataFrame(
            {
                "sku": ["A"] * 30,
                "data": pd.date_range("2026-11-01", periods=30),
                "previsao": [1.0] * 30,
                "status": ["avaliado"] * 30,
            }
        )
        produtos = pd.DataFrame(
            [
                {
                    "sku": "A",
                    "nome": "A",
                    "fornecedor_id": "F1",
                    "estoque_atual": 50,
                    "estoque_seguranca": 30,
                    "pedido_minimo": 1,
                    "multiplo_compra": 1,
                }
            ]
        )
        fornecedores = pd.DataFrame(
            [{"fornecedor_id": "F1", "nome": "F1", "prazo_dias": 2}]
        )
        _, recomendacoes = planejar_estoque(
            previsao, produtos, fornecedores, revisao_dias=3
        )
        self.assertTrue(recomendacoes["primeira_falta"].isna().all())
        self.assertFalse(recomendacoes["excesso"].any())
        self.assertEqual(
            recomendacoes.iloc[0]["status_agendamento"], "compra_programada"
        )
        self.assertEqual(len(recomendacoes.loc[precisam_revisao(recomendacoes)]), 1)


class TestDashboard(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(
            "os.environ", {"STOCKMIND_DB": str(Path(self.temp.name) / "test.sqlite3")}
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def app(self):
        return AppTest.from_file(str(Path(__file__).with_name("app.py"))).run(
            timeout=60
        )

    def test_carteira_multiplos_produtos(self):
        app = self.app()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "4")
        self.assertTrue(
            any("Carteira fictícia" in radio.options for radio in app.radio)
        )
        self.assertEqual(len(app.tabs), 6)
        self.assertEqual(app.tabs[0].label, "Decisões de reposição")
        self.assertTrue(
            any("SEM-005" in frame.value.to_string() for frame in app.dataframe)
        )

    def test_exemplo_antigo_continua_disponivel(self):
        app = self.app()
        app.radio[0].set_value("Exemplo de um produto").run(timeout=60)
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "1")
        self.assertTrue(
            any("PRODUTO-001" in select.options for select in app.selectbox)
        )

    def test_exemplo_sazonal_e_modelo_anual_disponivel(self):
        app = self.app()
        app.radio[0].set_value("Sazonalidade anual").run(timeout=90)
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "1")
        self.assertTrue(
            any(
                "Regressão com ciclo anual" in frame.value.to_string()
                for frame in app.dataframe
            )
        )

    def test_aplica_estimativas_com_amostras_sem_alterar_cadastro(self):
        app = self.app()
        next(
            c
            for c in app.checkbox
            if c.label == "Aplicar prazo sugerido pelo histórico de entregas"
        ).set_value(True).run(timeout=90)
        next(
            c
            for c in app.checkbox
            if c.label == "Aplicar estoque de segurança calculado"
        ).set_value(True).run(timeout=90)
        self.assertFalse(app.exception)
        table = next(
            frame.value
            for frame in app.dataframe
            if "Segurança sugerida" in frame.value.columns
        )
        self.assertTrue(table["Aplicado nesta análise"].any())

    def test_avaliacao_de_politicas_conclui_e_expoe_limite_censurado(self):
        app = self.app()
        next(
            c
            for c in app.checkbox
            if c.label == "Avaliar políticas de reposição no histórico"
        ).set_value(True).run(timeout=120)
        self.assertFalse(app.exception)
        summary = next(
            frame.value
            for frame in app.dataframe
            if "Custo estimado do cenário" in frame.value.columns
        )
        self.assertEqual(len(summary), 15)
        self.assertTrue(
            summary.loc[summary["Produto"].eq("CAC-003"), "Situação"]
            .str.contains("censurada", case=False)
            .all()
        )
        self.assertTrue(any("Período: 30 dias" in text.value for text in app.markdown))

    def test_demanda_totalmente_censurada_exibe_diagnostico_e_salva(self):
        from stockmind.data import ler_csv as real_read

        def censored(source):
            result = real_read(source)
            if Path(source).name == "vendas_multiplos_exemplo.csv":
                result["disponivel"] = 0
            return result

        with patch("stockmind.data.ler_csv", side_effect=censored):
            app = self.app()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value, "0")
            self.assertTrue(
                any(
                    "Não há demanda observável" in message.value
                    for message in app.warning
                )
            )
            next(
                b
                for b in app.button
                if b.label == "Salvar análise e entradas no histórico"
            ).click().run(timeout=90)
            self.assertFalse(app.exception)
            self.assertTrue(
                any("Análise salva:" in message.value for message in app.success)
            )

    def test_upload_aguarda_arquivo(self):
        app = self.app()
        app.radio[0].set_value("Enviar CSV").run(timeout=60)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe), 0)

    def test_salva_analise_e_mostra_no_historico(self):
        app = self.app()
        button = next(
            b for b in app.button if b.label == "Salvar análise e entradas no histórico"
        )
        button.click().run(timeout=60)
        self.assertFalse(app.exception)
        self.assertTrue(
            any("Análise salva:" in message.value for message in app.success)
        )
        self.assertTrue(any(s.label == "Análise salva" for s in app.selectbox))

    def test_comparacao_de_horizontes_e_cenarios(self):
        app = self.app()
        self.assertFalse(app.exception)
        self.assertTrue(
            any(
                "Redução do MAE vs. semana anterior (%)" in frame.value.columns
                for frame in app.dataframe
            )
        )
        next(
            slider
            for slider in app.slider
            if slider.label == "Variação de demanda nos cenários (%)"
        ).set_value(40).run(timeout=60)
        self.assertFalse(app.exception)
        self.assertTrue(
            any(
                "40%" in caption.value and "sensibilidade" in caption.value
                for caption in app.caption
            )
        )
        self.assertTrue(
            any(
                "Cenário" in frame.value.columns and len(frame.value) == 3
                for frame in app.dataframe
            )
        )

    def test_filtro_de_excesso_e_agendamento_visivel(self):
        app = self.app()
        next(
            radio for radio in app.radio if radio.label == "Decisão a revisar"
        ).set_value("Excesso").run(timeout=60)
        self.assertFalse(app.exception)
        table = next(
            frame.value
            for frame in app.dataframe
            if "Motivo da revisão" in frame.value.columns
        )
        self.assertIn("Unidades acima do alvo de 30 dias", table.columns)
        self.assertFalse(table.empty)
        self.assertTrue(table["Possível excesso (30 dias)"].eq(True).all())

    def test_filtro_de_dados_nao_classifica_excesso_normal_como_falha(self):
        app = self.app()
        next(
            radio for radio in app.radio if radio.label == "Decisão a revisar"
        ).set_value("Dados insuficientes").run(timeout=60)
        self.assertFalse(app.exception)
        table = next(
            frame.value
            for frame in app.dataframe
            if "Motivo da revisão" in frame.value.columns
        )
        self.assertNotIn("CAC-003", table["Produto"].tolist())
        self.assertIn("SEM-005", table["Produto"].tolist())

    def test_horizonte_curto_mostra_limite_de_reposicao(self):
        app = self.app()
        next(s for s in app.selectbox if s.label == "Horizonte (dias)").set_value(
            7
        ).run(timeout=60)
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[2].value, "—")
        self.assertTrue(
            any(
                "Aumente o horizonte" in frame.value.to_string()
                for frame in app.dataframe
            )
        )


if __name__ == "__main__":
    unittest.main()
