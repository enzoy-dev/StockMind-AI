"""Verificações dos fluxos do dashboard com banco temporário."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from streamlit.testing.v1 import AppTest


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
        self.assertEqual(len(app.tabs), 4)
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
