using System;

// ---------------------------------------------------------------------------
// Wallet/Accounts.cs — Session-scoped identity manager
//
// HISTORY
// -------
// Original (atropa_pulsechain):
//   A static `pkeys` list of 20 Hardhat test keys, with `pkeys[0]` optionally
//   overridden by the DYSNOMIA_PRIVATE_KEY environment variable. Simple and
//   convenient for local test networks, but unsuitable for a live wallet:
//   env-vars are visible to other processes and easy to leak in logs/scripts.
//
// This version (C-Dysnomia / Joey wallet):
//   Replaces the plaintext key list with an AES-256-GCM encrypted profile
//   written to disk outside the repository (%APPDATA%/dysnomia/profile.dat).
//   The private key is never stored in the repo, never exported to an env var,
//   and never held in memory longer than the process lifetime.
//
// PASSPHRASE RESOLUTION ORDER (first non-null value wins)
//   1. Explicit argument passed to Load() / Setup()
//   2. Environment variable DYS_PIN  (useful for CI / automated sessions)
//   3. Interactive console prompt (masked input, hidden while typing)
//
// TYPICAL SESSION FLOW
//   First run  — Accounts.Setup("0x<joey-private-key>")
//                  → prompts for a passphrase
//                  → writes encrypted profile.dat
//                  → caches key in memory for the rest of the session
//
//   Later runs — Accounts.Load()
//                  → reads profile.dat, decrypts with passphrase
//                  → caches key; subsequent calls return immediately
//
//   In code    — Accounts.Token
//                  → returns cached key string; throws if not yet loaded
//
// JOEY WALLET
//   Address : 0x17367877aF5A8D0Eb33ba5689A880f696386E24D  (PulseChain, chain 369)
//   GIBS LAU: 0x66a08aa12da955eb63d7ac121a88b2b210a07b03
//   The private key for this address lives solely in profile.dat and nowhere else.
// ---------------------------------------------------------------------------

namespace Wallet
{
    public static class Accounts
    {
        /// <summary>
        /// Environment variable for non-interactive passphrase delivery.
        /// Set DYS_PIN to the profile passphrase before launching to skip the prompt.
        /// </summary>
        public const string PhraseEnvVar = "DYS_PIN";

        private static string? _token;
        private static readonly object _sync = new();
        private static readonly ProfileManager _profile = new();

        /// <summary>Returns true once the private key has been loaded into memory.</summary>
        public static bool IsLoaded => _token != null;

        /// <summary>
        /// Returns the active private key, decrypting from disk on the first call.
        ///
        /// Thread-safe double-checked lock — subsequent calls return the cached
        /// value immediately without touching disk or re-prompting.
        /// </summary>
        /// <param name="passphrase">
        /// Optional explicit passphrase. If null, falls back to DYS_PIN env var,
        /// then an interactive masked console prompt.
        /// </param>
        /// <exception cref="InvalidOperationException">
        /// No profile exists on disk — run Setup() first.
        /// </exception>
        /// <exception cref="System.Security.Cryptography.CryptographicException">
        /// Wrong passphrase, or the profile file has been tampered with.
        /// </exception>
        public static string Load(string? passphrase = null)
        {
            if (_token is not null) return _token;

            lock (_sync)
            {
                if (_token is not null) return _token;

                if (!_profile.HasProfile)
                    throw new InvalidOperationException(
                        "No profile found. Run Accounts.Setup(\"0x<private-key>\") to initialize.");

                passphrase ??= Environment.GetEnvironmentVariable(PhraseEnvVar);
                passphrase ??= ReadPassphrase("Unlock profile: ");

                _token = _profile.Restore(passphrase);
                return _token;
            }
        }

        /// <summary>
        /// First-time setup: encrypts the private key and writes profile.dat to disk.
        /// Also caches the key for the current session so Load() is not needed afterward.
        ///
        /// Safe to call again to rotate the passphrase on an existing profile —
        /// ProfileManager always generates a fresh salt and nonce on each Seal().
        /// </summary>
        /// <param name="token">The raw private key to protect (e.g. "0xabc123...").</param>
        /// <param name="passphrase">
        /// Optional explicit passphrase. If null, falls back to DYS_PIN env var,
        /// then an interactive masked console prompt.
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
        /// The active private key.
        /// Throws if not yet loaded — call Load() or Setup() first.
        /// </summary>
        public static string Token =>
            _token ?? throw new InvalidOperationException(
                "Profile is locked. Call Accounts.Load() first.");

        /// <summary>
        /// Clears the in-memory key without touching disk.
        /// Call at session end or on error paths that require re-authentication.
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

            pkeys.Add("0x689af8efa8c651a91ad287602527f3af2fe9f6501a7ac4b061667b5a93e037fd");
            pkeys.Add("0xde9be858da4a475276426320d5e9262ecfc3ba460bfac56360bfa6c4c28b4ee0");
            pkeys.Add("0xdf57089febbacf7ba0bc227dafbffa9fc08a93fdc68e1e42411a14efcf23656e");
        }
    }
}
