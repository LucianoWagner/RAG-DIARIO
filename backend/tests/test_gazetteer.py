from app.ingestion.enrichers.gazetteer import Gazetteer


def _gazetteer() -> Gazetteer:
    return Gazetteer(
        city="Argentina",
        aliases=["Argentina", "CABA", "La Plata"],
        institutions=[],
        keywords=[],
        direct_argentina_sections=[],
    )


def test_find_locations_no_detecta_caba_dentro_de_caballito():
    locations = _gazetteer().find_locations("La novela menciona caballito como imagen poetica.")

    assert "CABA" not in locations


def test_find_locations_detecta_caba_como_sigla_independiente():
    locations = _gazetteer().find_locations("El informe menciona CABA y La Plata.")

    assert "CABA" in locations
    assert "La Plata" in locations
