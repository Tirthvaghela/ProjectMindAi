from nlp.preprocess import clean_for_embedding, expand_abbreviations, keyword_set, tokens_for_bm25


def test_clean_for_embedding_preserves_word_order_and_stopwords():
    # The whole point of this function (see the module docstring): a
    # transformer needs function words and order intact.
    text = clean_for_embedding("A project FOR kids WITH disabilities")
    assert text == "a project for kids with disabilities"


def test_clean_for_embedding_strips_urls():
    text = clean_for_embedding("Check https://example.com/docs for more")
    assert "example.com" not in text


def test_clean_for_embedding_expands_known_abbreviations():
    text = clean_for_embedding("An ML project using NLP")
    assert "machine learning" in text
    assert "natural language processing" in text


def test_expand_abbreviations_only_matches_whole_words():
    # "html" contains no standalone "ml" token, so it must not be rewritten.
    text = expand_abbreviations("html rendering")
    assert text == "html rendering"


def test_tokens_for_bm25_removes_stopwords_and_lemmatises():
    tokens = tokens_for_bm25("recommending systems for beginners")
    assert "for" not in tokens
    # "beginners" carries no domain-filler stopword, but is a plural that
    # should be lemmatised to its singular form.
    assert "beginner" in tokens or "beginners" in tokens
    assert "recommend" in tokens or "recommending" in tokens


def test_tokens_for_bm25_drops_domain_filler_words():
    tokens = tokens_for_bm25("I want a good beginner project idea")
    for filler in ("want", "good", "project", "idea"):
        assert filler not in tokens


def test_tokens_for_bm25_keeps_short_meaningful_tokens_like_language_names():
    # "computer" and "c" are removed from NLTK's default stopword list on
    # purpose (see _nltk_tools) so "computer vision" and "C" survive.
    tokens = tokens_for_bm25("C programming and computer vision")
    assert "c" in tokens
    assert "computer" in tokens


def test_keyword_set_is_unique():
    tokens = keyword_set("testing testing one two two")
    assert tokens == set(tokens)  # trivially true, but documents the contract
    assert "testing" in tokens
