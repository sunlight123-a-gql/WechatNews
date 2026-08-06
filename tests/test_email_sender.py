import unittest
from unittest.mock import MagicMock, patch

from src.email_sender import EmailSettings, send_html_email, settings_from_env


class EmailSenderTests(unittest.TestCase):
    def test_settings_from_env_loads_multiple_recipients(self):
        settings = settings_from_env(
            {
                "SMTP_HOST": "smtp.example.com",
                "SMTP_PORT": "465",
                "SMTP_SECURITY": "ssl",
                "SMTP_USERNAME": "sender@example.com",
                "SMTP_PASSWORD": "authorization-code",
                "EMAIL_TO": "first@example.com; second@example.com",
            }
        )

        self.assertEqual(settings.sender, "sender@example.com")
        self.assertEqual(settings.recipients, ("first@example.com", "second@example.com"))
        self.assertNotIn("authorization-code", repr(settings))

    def test_send_html_email_uses_authenticated_ssl(self):
        settings = EmailSettings(
            host="smtp.example.com",
            port=465,
            username="sender@example.com",
            password="authorization-code",
            sender="sender@example.com",
            recipients=("reader@example.com",),
        )
        client = MagicMock()
        client.__enter__.return_value = client

        with patch("src.email_sender.smtplib.SMTP_SSL", return_value=client) as smtp_ssl:
            send_html_email("<h1>Daily digest</h1>", "Daily News", settings=settings)

        smtp_ssl.assert_called_once()
        client.login.assert_called_once_with("sender@example.com", "authorization-code")
        message = client.send_message.call_args.args[0]
        self.assertEqual(message["Subject"], "Daily News")
        self.assertEqual(message["To"], "reader@example.com")
        self.assertIn("<h1>Daily digest</h1>", message.get_body(preferencelist=("html",)).get_content())

    def test_settings_from_env_rejects_missing_credentials(self):
        with self.assertRaisesRegex(RuntimeError, "SMTP_PASSWORD"):
            settings_from_env(
                {
                    "SMTP_HOST": "smtp.example.com",
                    "SMTP_USERNAME": "sender@example.com",
                    "EMAIL_TO": "reader@example.com",
                }
            )


if __name__ == "__main__":
    unittest.main()
