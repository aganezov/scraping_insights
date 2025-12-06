from insight_mine.utils.text import keep_by_lang


def test_is_lang_basic():
    assert keep_by_lang("This is an English sentence about scraping.", ["en"])
    assert keep_by_lang("Ceci est une phrase française.", ["fr"])
    # empty allowed list -> no filtering
    assert keep_by_lang("Hola mundo", [])
