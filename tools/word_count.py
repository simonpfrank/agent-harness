"""Count words in text."""


def word_count(text: str) -> str:
    """Count the number of words in the given text.

    Args:
        text: The text to count words in.

    Returns:
        The word count as a string.
    """
    return str(len(text.split()))
