using Dysnomia.Domain;
using Dysnomia.Domain.World;
using Nethereum.Web3.Accounts;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using Wallet;
using static System.Runtime.InteropServices.JavaScript.JSType;

namespace Dysnomia
{
    static public class Controller
    {
        static public Oracle Oracle;
        static public Wallet.Wallet LocalWallet;
        static public Wallet.Contracts LocalContracts;

        static Controller()
        {
            Oracle = new Oracle();
            Console.Error.WriteLine("[Controller] Oracle created");

            string rpc = System.Environment.GetEnvironmentVariable("DYSNOMIA_RPC") ?? "https://rpc.pulsechain.com";
            string solc = System.Environment.GetEnvironmentVariable("DYSNOMIA_SOLC") ?? "/usr/local/bin/solc";
            string repo = System.Environment.GetEnvironmentVariable("DYSNOMIA_REPO") ?? System.AppContext.BaseDirectory;

            Console.Error.WriteLine("[Controller] " +"Connecting to RPC: " + rpc);
            LocalWallet = new Wallet.Wallet(rpc);
            Console.Error.WriteLine("[Controller] " +"Wallet connected. Switching to account 0...");
            LocalWallet.SetOracleProcessString(Oracle.ProcessStringAndWait);
            LocalWallet.SwitchAccount(0);
            Console.Error.WriteLine("[Controller] " +"Account: " + LocalWallet.Account.Address);

            Wallet.Contracts.Init(solc, repo);
            LocalContracts = new Wallet.Contracts(LocalWallet);
            Console.Error.WriteLine("[Controller] " +"Contracts initialized. Enqueueing live alias load (0x01)...");

            // Opcode 0x01: load live PulseChain contract aliases (skip local deploy).
            // Enqueued twice: Phi()'s outer TryDequeue consumes the first; the inner
            // while(Count>0) processes it only when a second item is present.
            Oracle.Enqueue(new byte[] { 0x01 });
            Oracle.Enqueue(new byte[] { 0x01 });
            Console.Error.WriteLine("[Controller] " +"Controller ready.");
        }
    }
}
