
using System.Configuration;
using System.Numerics;
using Nethereum.Web3;
using Nethereum.Contracts.Services;
using Nethereum.Hex.HexTypes;
using Nethereum.RPC.Eth;
using Nethereum.Web3.Accounts;
using Nethereum.Contracts;
using Nethereum.RPC.Eth.DTOs;
using System.Reflection.Metadata;

// ---------------------------------------------------------------------------
// Wallet/Wallet.cs — Nethereum Web3 connection wrapper
//
// Adapted from: github.com/busytoby/atropa_pulsechain/Wallet/Wallet.cs
//
// CHANGES FROM UPSTREAM
// ---------------------
// 1. Key loading — Accounts.pkeys[0] → Accounts.Load()
//    Upstream loaded the key from a plaintext list (optionally from the
//    DYSNOMIA_PRIVATE_KEY env var). We now load from the AES-256-GCM
//    encrypted profile written by ProfileManager.  The key is never
//    stored in the repo, never in a plaintext env var, and is only held
//    in process memory for the lifetime of the session.
//
// 2. SwitchAccount removed
//    Upstream's SwitchAccount(int) cycled through Accounts.pkeys[N] to
//    operate as one of 20 Hardhat test accounts.  With a single encrypted
//    identity (Joey's wallet) there is no list to switch between.
//    If multi-account support is added later, create separate encrypted
//    profiles and instantiate one Wallet per identity.
//
// 3. w3 initialised with Account (signed mode)
//    Upstream created w3 = new Web3(ConnectionString) (read-only) then
//    re-created it with the Account only inside SwitchAccount.  Here we
//    attach the Account at construction so all transactions are signed
//    immediately without a second call.
//
// JOEY WALLET DETAILS
//    Address   : 0x17367877aF5A8D0Eb33ba5689A880f696386E24D
//    Chain     : PulseChain (chain 369)
//    GIBS LAU  : 0x66a08aa12da955eb63d7ac121a88b2b210a07b03
//    YUE wallet: 0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0
//    GIBS QING : 0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35
//
// FIRST-TIME SETUP (one-time, per machine)
//    Accounts.Setup("0x<joey-private-key>");
//    // Prompts for a passphrase, writes ~/.config/dysnomia/profile.dat
//
// TYPICAL SESSION USE
//    var wallet = new Wallet("https://rpc.pulsechain.com");
//    // Calls Accounts.Load() internally — prompts once if DYS_PIN not set.
//    // wallet.Account.Address == "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
//    // wallet.w3 is ready for signed transactions and contract calls.
//
// NON-INTERACTIVE / CI
//    Set DYS_PIN=<passphrase> in the environment before launching; no prompt.
// ---------------------------------------------------------------------------

namespace Wallet
{
    public class Wallet
    {
        // Sentinel used by the upstream alias system (Aliases.cs); preserved for compatibility.
        static public string _base = "þ";

        public string ConnectionString;
        public Web3 w3;
        public IEthApiContractService eth;
        public Account Account;
        internal OracleProcessString ProcessString;
        public delegate dynamic OracleProcessString(String A);

        /// <summary>
        /// Creates a Wallet connected to <paramref name="connectionString"/> and
        /// signed with the key stored in the encrypted profile.
        ///
        /// Calls Accounts.Load() on first use — see Accounts.cs for passphrase
        /// resolution order (explicit arg → DYS_PIN env var → interactive prompt).
        /// </summary>
        /// <param name="connectionString">
        /// RPC endpoint for the target chain.
        /// PulseChain mainnet: "https://rpc.pulsechain.com"  (chain 369)
        /// </param>
        public Wallet(string connectionString)
        {
            ConnectionString = connectionString;

            // Load the encrypted private key and create a signed Nethereum account.
            // Accounts.Load() is idempotent after the first call — cached in memory.
            Account = new Account(Accounts.Load());

            // Initialise Web3 with the signed account so all eth.TransactionManager
            // calls are automatically signed without a separate SwitchAccount step.
            w3 = new Web3(Account, ConnectionString);
            eth = w3.Eth;

            // Subscribe to TransferEvents from the current block onward so Contracts.cs
            // can track incoming/outgoing token transfers during the session.
            Task<HexBigInteger> _b = w3.Eth.Blocks.GetBlockNumber.SendRequestAsync();
            _b.Wait();
            HexBigInteger latestBlock = new HexBigInteger(_b.Result.ToUlong() + 1);
            Event<Events.TransferEvent> TransferEvent = w3.Eth.GetEvent<Events.TransferEvent>();
            NewFilterInput _n = TransferEvent.CreateFilterInput();
            _n.FromBlock = new BlockParameter(latestBlock);
            Contracts.Logs.Add(new wEvent(TransferEvent, _n, "TransferEvent"));
        }

        public void SetOracleProcessString(OracleProcessString _o) {
            ProcessString = _o;
        }

        // NOTE: SwitchAccount(int) was present in the upstream atropa_pulsechain
        // Wallet.cs and allowed cycling through 20 Hardhat test keys stored in
        // Accounts.pkeys.  It has been removed here because the encrypted profile
        // holds a single live key (Joey's wallet).  If you need to operate as a
        // different account, create a second encrypted profile at a custom path
        // (new ProfileManager("/path/to/alt.dat")) and instantiate a new Wallet.

        /// <summary>
        /// Returns the native token (PLS on PulseChain) balance for <paramref name="Address"/>.
        /// Returned value is in wei; divide by 10^18 for PLS.
        /// </summary>
        public HexBigInteger EthGetBalance(string Address)
        {
            Task<HexBigInteger> _t = eth.GetBalance.SendRequestAsync(Address);
            _t.Wait();
            return _t.Result;
        }
    }

}
