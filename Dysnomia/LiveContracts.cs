using System;
using System.Threading.Tasks;

namespace Dysnomia
{
    /// <summary>
    /// Maps live PulseChain (chain 369) contract addresses to their compiled ABIs.
    /// Called via Oracle opcode 0x01 on startup — skips the local deploy sequence.
    ///
    /// Phase 1: core game contracts (compiled from dysnomia/*.sol).
    /// Minter contracts (BUREAU, FEDERAL, TREASURY) require @openzeppelin and will be
    /// added once npm install is set up for the solidity/ directory.
    /// </summary>
    public static class LiveContracts
    {
        private static void Log(string msg) => Console.Error.WriteLine("[LiveContracts] " + msg);

        private static async Task TryLoad(string alias, string address, string solFile)
        {
            try {
                await Controller.LocalContracts.AddAliasWithABI(alias, address, solFile);
                Log(alias + " OK  ← " + address);
            } catch (Exception ex) {
                Log("WARN: " + alias + " failed: " + ex.Message);
            }
        }

        public static async Task Initialize()
        {
            Log("Loading live PulseChain contracts...");

            // ── Core ERC20 / token contracts (dysnomia/01_dysnomia.sol) ─────────────
            // AFFECTION — universal gateway token (1:1 to any token)
            await TryLoad("AFFECTION", "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D",
                "dysnomia/01_dysnomia.sol");

            // CROWS — social credential token (25+ = bouncer access to venues)
            await TryLoad("CROWS", "0x203e366A1821570b2f84Ff5ae8B3BdeB48Dc4fa1",
                "dysnomia/01_dysnomia.sol");

            // WM (MV) — funding key, required 1:1 to create new minter tokens
            await TryLoad("WM", "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29",
                "dysnomia/01_dysnomia.sol");

            // Atropa ERC20 — base token contract
            await TryLoad("ATROPA", "0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6",
                "dysnomia/01_dysnomia.sol");

            // ── Game controller ──────────────────────────────────────────────────────
            // VOID — Enter(), Chat(), SetAttribute(), Alias(), AddLibrary(), Log()
            await TryLoad("VOID", "0x965B0d74591bF30327075A247C47dBf487dCff08",
                "dysnomia/10_void.sol");

            // LAU factory — deploys new LAU tokens via Enter()
            await TryLoad("LAUFactory", "0x965B0d74591bF30327075A247C47dBf487dCff08",
                "dysnomia/11c_laufactory.sol");

            // ── Note: BUREAU/FEDERAL/TREASURY minters require @openzeppelin ──────────
            // Run: npm install in solidity/ to enable, then re-add here.

            Log("Live contracts ready. Wallet: " + Controller.LocalWallet.Account.Address);
        }
    }
}
