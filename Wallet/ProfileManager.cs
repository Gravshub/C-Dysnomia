using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;

// ---------------------------------------------------------------------------
// Wallet/ProfileManager.cs — Encrypted private-key storage
//
// Handles the low-level encrypt/decrypt of the identity profile that
// Accounts.cs exposes at a higher level. Nothing in this file is specific
// to Dysnomia game logic — it is a general-purpose AES-256-GCM sealed store.
//
// STORAGE FORMAT  (binary, fields concatenated, no headers or framing)
//   salt       16 bytes   — random per Seal(); input to PBKDF2 key derivation
//   nonce      12 bytes   — random per Seal(); required by AES-GCM
//   tag        16 bytes   — AES-GCM authentication tag; verifies integrity
//   ciphertext variable   — UTF-8 encoded private key, encrypted
//
//   Total overhead: 44 bytes.  A typical 66-char hex private key ("0x" + 64)
//   produces a 110-byte profile.dat file.
//
// KEY DERIVATION
//   Algorithm : PBKDF2-SHA256
//   Iterations: 100,000  (NIST SP 800-132 minimum for interactive logins)
//   Output    : 256 bits → AES-256 key
//
// INTEGRITY
//   AES-GCM provides authenticated encryption.  Any wrong passphrase or
//   byte-level file tampering causes AesGcm.Decrypt to throw
//   CryptographicException before any plaintext is returned.
//
// DEFAULT PROFILE PATH
//   Windows : %APPDATA%\dysnomia\profile.dat
//   Linux   : ~/.config/dysnomia/profile.dat   (ApplicationData on Linux)
//   macOS   : ~/Library/Application Support/dysnomia/profile.dat
//
//   The directory is created automatically on first Seal().
//   The path can be overridden via the ProfileManager(string) constructor
//   (useful for integration tests or alternate accounts).
// ---------------------------------------------------------------------------

namespace Wallet
{
    public sealed class ProfileManager
    {
        private const int SaltSize   = 16;
        private const int NonceSize  = 12;
        private const int TagSize    = 16;
        private const int KeySize    = 32;       // AES-256
        private const int Iterations = 100_000;

        private static readonly string DefaultProfileDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "dysnomia"
        );

        private readonly string _profilePath;

        /// <param name="profilePath">
        /// Full path to the profile file.  If null, uses the platform default
        /// (%APPDATA%/dysnomia/profile.dat on Windows; see class header).
        /// </param>
        public ProfileManager(string? profilePath = null)
        {
            if (profilePath != null)
            {
                _profilePath = profilePath;
            }
            else
            {
                Directory.CreateDirectory(DefaultProfileDir);
                _profilePath = Path.Combine(DefaultProfileDir, "profile.dat");
            }
        }

        /// <summary>Returns true if a sealed profile file exists on disk.</summary>
        public bool HasProfile => File.Exists(_profilePath);

        /// <summary>
        /// Encrypts <paramref name="token"/> with <paramref name="passphrase"/>
        /// and writes the sealed profile to disk.
        ///
        /// Generates fresh random salt and nonce on every call, so repeated
        /// calls with the same passphrase produce different ciphertext —
        /// safe for passphrase rotation.
        /// </summary>
        public void Seal(string passphrase, string token)
        {
            byte[] salt  = RandomNumberGenerator.GetBytes(SaltSize);
            byte[] nonce = RandomNumberGenerator.GetBytes(NonceSize);
            byte[] key   = DeriveKey(passphrase, salt);

            byte[] plaintext  = Encoding.UTF8.GetBytes(token);
            byte[] ciphertext = new byte[plaintext.Length];
            byte[] tag        = new byte[TagSize];

            using (var aes = new AesGcm(key, TagSize))
                aes.Encrypt(nonce, plaintext, ciphertext, tag);

            // Ensure parent directory exists before writing
            string? dir = Path.GetDirectoryName(_profilePath);
            if (dir is { Length: > 0 })
                Directory.CreateDirectory(dir);

            // Write salt | nonce | tag | ciphertext  (no framing — fixed offsets)
            using var ms = new MemoryStream(SaltSize + NonceSize + TagSize + ciphertext.Length);
            ms.Write(salt);
            ms.Write(nonce);
            ms.Write(tag);
            ms.Write(ciphertext);

            File.WriteAllBytes(_profilePath, ms.ToArray());
        }

        /// <summary>
        /// Decrypts the profile from disk using <paramref name="passphrase"/>.
        /// Returns the original plaintext token (private key string).
        /// </summary>
        /// <exception cref="FileNotFoundException">No profile file exists.</exception>
        /// <exception cref="InvalidDataException">Profile data is malformed (too short).</exception>
        /// <exception cref="CryptographicException">
        /// Wrong passphrase or the file has been tampered with.
        /// </exception>
        public string Restore(string passphrase)
        {
            if (!HasProfile)
                throw new FileNotFoundException(
                    "No profile found. Call Seal() to create one.", _profilePath);

            byte[] data   = File.ReadAllBytes(_profilePath);
            int    minLen = SaltSize + NonceSize + TagSize + 1;

            if (data.Length < minLen)
                throw new InvalidDataException(
                    $"Profile data is too short ({data.Length} bytes; expected ≥ {minLen}).");

            // Unpack fixed-offset fields
            byte[] salt       = data[0..SaltSize];
            byte[] nonce      = data[SaltSize..(SaltSize + NonceSize)];
            byte[] tag        = data[(SaltSize + NonceSize)..(SaltSize + NonceSize + TagSize)];
            byte[] ciphertext = data[(SaltSize + NonceSize + TagSize)..];

            byte[] key       = DeriveKey(passphrase, salt);
            byte[] plaintext = new byte[ciphertext.Length];

            // Throws CryptographicException if passphrase is wrong or data is tampered
            using (var aes = new AesGcm(key, TagSize))
                aes.Decrypt(nonce, ciphertext, tag, plaintext);

            return Encoding.UTF8.GetString(plaintext);
        }

        // PBKDF2-SHA256, 100k iterations, 256-bit output — no external dependencies.
        private static byte[] DeriveKey(string passphrase, byte[] salt) =>
            Rfc2898DeriveBytes.Pbkdf2(
                Encoding.UTF8.GetBytes(passphrase),
                salt,
                Iterations,
                HashAlgorithmName.SHA256,
                KeySize
            );
    }
}
