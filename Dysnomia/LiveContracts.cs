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

            // ── Player LAU token ─────────────────────────────────────────────────────
            // GIBS (Gibson) — Joey's LAU token deployed at 0x66a08aa12da955eb63d7ac121a88b2b210a07b03
            await TryLoad("GIBS", "0x66a08aa12da955eb63d7ac121a88b2b210a07b03",
                "dysnomia/11_lau.sol");

            // ── DysnomiaSelfSnipev4 (DSS) — Joey's self-sniper ───────────────────────
            // Deployed at 0x91Df693177eE5C81016d0B7c4c2052A7d229c031 (block 25887000)
            await TryLoad("DysnomiaSelfSnipev4", "0x91Df693177eE5C81016d0B7c4c2052A7d229c031",
                "dysnomia/etc/DysnomiaSelfSnipev4.sol");

            // ── Player YUE wallet — Joey's in-game inventory ────────────────────────
            // Created via SEI.Start(GIBS, "Gibson Wallet", "GIBSw") block 25,893,644
            await TryLoad("YUE", "0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0",
                "dysnomia/domain/yue.sol");

            // ── GIBS QING venue — Joey's GIBS trading marketplace ───────────────────
            // Created via MAP.New(GIBS) block 25,893,651; Asset = GIBS
            await TryLoad("GIBS_QING", "0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35",
                "dysnomia/domain/dan/03_qing.sol");

            // ── Processing chain contracts (verified on-chain 2026-02-27) ────────────
            // Traced from Noumenon's YUE (0x935a694...) → CHAN → XIE → XIA → MAI → QI → ZUO → CHO
            // SEI verified: Start(address,string,string) deploys YUE, registers in CHO
            await TryLoad("SEI",  "0x3dC54d46e030C42979f33C9992348a990acb6067",
                "dysnomia/domain/tang/01_sei.sol");
            // MAP verified: New(address) deploys QING venue, nonce=272 (272 venues created)
            await TryLoad("MAP",  "0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75",
                "dysnomia/domain/map.sol");
            await TryLoad("CHAN", "0xe250bf9729076B14A8399794B61C72d0F4AeFcd8",
                "dysnomia/domain/sky/01_chan.sol");
            await TryLoad("CHO",  "0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB",
                "dysnomia/domain/dan/01_cho.sol");
            await TryLoad("XIE",  "0x4Df51741F2926525A21bF63E4769bA70633D2792",
                "dysnomia/01_dysnomia.sol");   // Fornax SHIO = XIE token
            await TryLoad("XIA",  "0x7f4a4DD4a6f233d2D82BE38b2F9fc0Fef46f25FA",
                "dysnomia/01_dysnomia.sol");
            await TryLoad("MAI",  "0xc48B0a4E79eF302c8Eb5be71F562d08fB8E6A3d8",
                "dysnomia/01_dysnomia.sol");
            await TryLoad("QI",   "0x4d9Ce396BE95dbc5F71808c38107eB7422FD9a03",
                "dysnomia/01_dysnomia.sol");
            await TryLoad("ZUO",  "0xb0Ba7D36B7F0505879179ecE7401F24eB653c6E1",
                "dysnomia/domain/dan/03_qing.sol");  // Game's built-in QING

            // ── Note: BUREAU/FEDERAL/TREASURY minters require @openzeppelin ──────────
            // Run: npm install in solidity/ to enable, then re-add here.

            Log("Live contracts ready. Wallet: " + Controller.LocalWallet.Account.Address);
        }
    }
}
