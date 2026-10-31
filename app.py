"""Entrada Streamlit: python -m streamlit run app.py."""

from stockmind.ui.components import precisam_revisao as precisam_revisao


def main():
    from stockmind.ui.dashboard import main as dashboard

    dashboard()


if __name__ == "__main__":
    main()
