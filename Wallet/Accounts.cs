using System;

namespace Dysnomia.Wallet
{
    /// <summary>
    /// Session-scoped identity manager.
    ///
    /// Loads the identity token once per process lifetime and caches it in
    /// memory. The token is never written back to disk after the initial Seal.
    ///
    /// Passphrase resolution order (first non-null value wins):
    ///   1. Explicit argument passed to Load() / Setup()
    ///   2. Environment variable DYS_PIN
    ///   3. Interactive console prompt (masked input)
    ///
    /// Typical session flow:
    ///   First run  — Accounts.Setup("0xYourTokenHere")  → seals + caches
    ///   Later runs — Accounts.Load()                    → restores from disk + caches
    ///   In code    — Accounts.Token                     → returns cached value
    /// </summary>
    public static class Accounts
    {
        /// <summary>
        /// Environment variable name for non-interactive passphrase delivery.
        /// Useful for automated or CI sessions.
        /// </summary>
        public const string PhraseEnvVar = "DYS_PIN";

        private static string? _token;
        private static readonly object _sync = new();
        private static readonly ProfileManager _profile = new();

        /// <summary>Returns true once the token has been loaded into memory.</summary>
        public static bool IsLoaded => _token != null;

        /// <summary>
        /// Returns the active identity token, loading from disk on the first call.
        ///
        /// After the first successful call the value is cached; subsequent calls
        /// return immediately without touching disk or re-prompting.
        /// </summary>
        /// <param name="passphrase">
        /// Optional explicit passphrase. If null, falls back to DYS_PIN env var
        /// then interactive prompt.
        /// </param>
        /// <exception cref="InvalidOperationException">
        /// No profile exists on disk — run Setup() first.
        /// </exception>
        /// <exception cref="System.Security.Cryptography.CryptographicException">
        /// Wrong passphrase or profile file is corrupted.
        /// </exception>
        public static string Load(string? passphrase = null)
        {
            if (_token is not null) return _token;

            lock (_sync)
            {
                if (_token is not null) return _token;

                if (!_profile.HasProfile)
                    throw new InvalidOperationException(
                        "No profile found. Run Accounts.Setup() to initialize.");

                passphrase ??= Environment.GetEnvironmentVariable(PhraseEnvVar);
                passphrase ??= ReadPassphrase("Unlock profile: ");

                _token = _profile.Restore(passphrase);
                return _token;
            }
        }

        /// <summary>
        /// First-time setup: seals the provided identity token and caches it for
        /// the current session.
        ///
        /// Safe to call again to rotate the passphrase on an existing profile.
        /// </summary>
        /// <param name="token">The raw identity token to protect.</param>
        /// <param name="passphrase">
        /// Optional explicit passphrase. If null, falls back to DYS_PIN env var
        /// then interactive prompt.
        /// </param>
        public static void Setup(string token, string? passphrase = null)
        {
            passphrase ??= Environment.GetEnvironmentVariable(PhraseEnvVar);
            passphrase ??= ReadPassphrase("Create passphrase: ");

            _profile.Seal(passphrase, token);

            lock (_sync)
                _token = token;
        }

        /// <summary>
        /// The active identity token.
        /// Throws if not yet loaded — call Load() or Setup() first.
        /// </summary>
        public static string Token =>
            _token ?? throw new InvalidOperationException(
                "Profile is locked. Call Accounts.Load() first.");

        /// <summary>
        /// Clears the in-memory token without touching disk.
        /// Call when the session ends or on error paths that require re-auth.
        /// </summary>
        public static void Lock()
        {
            lock (_sync)
                _token = null;
        }

        // Reads a passphrase from the console without echoing characters.
        private static string ReadPassphrase(string prompt)
        {
            Console.Write(prompt);
            var buf = new System.Text.StringBuilder();

            while (true)
            {
                var key = Console.ReadKey(intercept: true);

                if (key.Key == ConsoleKey.Enter)
                    break;

                if (key.Key == ConsoleKey.Backspace)
                {
                    if (buf.Length > 0)
                        buf.Remove(buf.Length - 1, 1);
                }
                else if (key.KeyChar != '\0')
                {
                    buf.Append(key.KeyChar);
                }
            }

            Console.WriteLine();
            return buf.ToString();
        }
    }
}
