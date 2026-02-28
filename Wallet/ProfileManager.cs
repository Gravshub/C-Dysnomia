using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;

namespace Dysnomia.Wallet
{
    /// <summary>
    /// Manages persistent identity profiles across sessions.
    ///
    /// Storage format (binary, all fields concatenated):
    ///   salt(16) | nonce(12) | tag(16) | ciphertext(variable)
    ///
    /// Algorithm: AES-256-GCM with PBKDF2-SHA256 key derivation.
    /// The authentication tag ensures both confidentiality and integrity —
    /// any wrong passphrase or tampered file raises CryptographicException.
    /// </summary>
    public sealed class ProfileManager
    {
        private const int SaltSize  = 16;
        private const int NonceSize = 12;
        private const int TagSize   = 16;
        private const int KeySize   = 32;  // AES-256
        private const int Iterations = 100_000;

        private static readonly string DefaultProfileDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "dysnomia"
        );

        private readonly string _profilePath;

        /// <param name="profilePath">
        /// Full path to the profile file. Defaults to
        /// %APPDATA%/dysnomia/profile.dat  (Windows) or
        /// ~/.config/dysnomia/profile.dat  (Linux/macOS via ApplicationData).
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
        /// Seals an identity token with the given passphrase and writes it to disk.
        /// Safe to call again to rotate the passphrase — always generates fresh
        /// random salt and nonce.
        /// </summary>
        /// <param name="passphrase">The passphrase used to derive the encryption key.</param>
        /// <param name="token">The raw identity token to protect.</param>
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

            // Ensure parent directory exists
            string? dir = Path.GetDirectoryName(_profilePath);
            if (dir is { Length: > 0 })
                Directory.CreateDirectory(dir);

            using var ms = new MemoryStream(SaltSize + NonceSize + TagSize + ciphertext.Length);
            ms.Write(salt);
            ms.Write(nonce);
            ms.Write(tag);
            ms.Write(ciphertext);

            File.WriteAllBytes(_profilePath, ms.ToArray());
        }

        /// <summary>
        /// Restores the identity token from disk using the given passphrase.
        /// </summary>
        /// <exception cref="FileNotFoundException">No profile file exists.</exception>
        /// <exception cref="InvalidDataException">Profile data is malformed.</exception>
        /// <exception cref="CryptographicException">
        /// Wrong passphrase or the file has been tampered with.
        /// </exception>
        public string Restore(string passphrase)
        {
            if (!HasProfile)
                throw new FileNotFoundException(
                    "No profile found. Call Seal() to create one.", _profilePath);

            byte[] data = File.ReadAllBytes(_profilePath);
            int minLen  = SaltSize + NonceSize + TagSize + 1;

            if (data.Length < minLen)
                throw new InvalidDataException(
                    $"Profile data is too short ({data.Length} bytes; expected at least {minLen}).");

            byte[] salt       = data[0..SaltSize];
            byte[] nonce      = data[SaltSize..(SaltSize + NonceSize)];
            byte[] tag        = data[(SaltSize + NonceSize)..(SaltSize + NonceSize + TagSize)];
            byte[] ciphertext = data[(SaltSize + NonceSize + TagSize)..];

            byte[] key       = DeriveKey(passphrase, salt);
            byte[] plaintext = new byte[ciphertext.Length];

            // AesGcm.Decrypt throws CryptographicException on auth failure
            using (var aes = new AesGcm(key, TagSize))
                aes.Decrypt(nonce, ciphertext, tag, plaintext);

            return Encoding.UTF8.GetString(plaintext);
        }

        // PBKDF2-SHA256, 100k iterations, 256-bit output
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
