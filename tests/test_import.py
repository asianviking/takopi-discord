"""Basic import tests."""


def test_import() -> None:
    """Test that the package can be imported."""
    import takopi_discord

    assert takopi_discord.BACKEND is not None
