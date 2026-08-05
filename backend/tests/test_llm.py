from unittest.mock import MagicMock, patch

import pytest

from app.core.llm import AiProviderError, embed_text, generate_text, generate_with_tools


class TestGenerateTextFailures:
    def test_sdk_exception_becomes_ai_provider_error(self) -> None:
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("429 RESOURCE_EXHAUSTED")
        with patch("app.core.llm._get_client", return_value=client):
            with pytest.raises(AiProviderError):
                generate_text("hi")

    def test_none_response_text_becomes_ai_provider_error(self) -> None:
        client = MagicMock()
        client.models.generate_content.return_value = MagicMock(text=None)
        with patch("app.core.llm._get_client", return_value=client):
            with pytest.raises(AiProviderError):
                generate_text("hi")


class TestGenerateWithToolsFailures:
    def test_sdk_exception_becomes_ai_provider_error(self) -> None:
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("network error")
        with patch("app.core.llm._get_client", return_value=client):
            with pytest.raises(AiProviderError):
                generate_with_tools("hi", [])


class TestEmbedTextFailures:
    def test_sdk_exception_becomes_ai_provider_error(self) -> None:
        client = MagicMock()
        client.models.embed_content.side_effect = RuntimeError("auth error")
        with patch("app.core.llm._get_client", return_value=client):
            with pytest.raises(AiProviderError):
                embed_text("hi")

    def test_empty_embeddings_becomes_ai_provider_error(self) -> None:
        client = MagicMock()
        client.models.embed_content.return_value = MagicMock(embeddings=[])
        with patch("app.core.llm._get_client", return_value=client):
            with pytest.raises(AiProviderError):
                embed_text("hi")
