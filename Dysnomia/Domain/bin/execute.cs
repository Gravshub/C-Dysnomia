// execute.cs — Universal contract call command
//
// This is the FALLBACK handler. Command.cs uses it in two ways:
//
//   1. FALLBACK (unknown command):
//        Input:  "VOID Chat hello"
//        Result: Alias="VOID", Args=["Chat","hello"]
//        → call ExecuteWithAliases("VOID", "Chat", "hello")
//
//   2. DIRECT call:
//        Input:  "execute VOID Chat hello"
//        Result: Alias="execute", Args=["VOID","Chat","hello"]
//        → detect Alias=="execute", shift Args: contract=Args[0], func=Args[1]
//
//   3. DIRECT with account switch (correct form — no leading 0):
//        Input:  "execute VOID Chat hello"  (from wallet account 0 by default)
//        Note:   Do NOT use "execute 0 VOID Chat hello" — that triggered the old
//                Alias-overwrite bug where Args[0]="0" was written into Alias.
//
// BUG HISTORY: The old "execute 0 X func arg" form overwrote Alias with "0"
// (the account number string) before resolving the contract, breaking the call.
// Fix: account switching is NOT embedded in execute — switch via the `account`
// command or Controller.LocalWallet.SwitchAccount() before calling.

using Dysnomia.Lib;
using System.Text;

namespace Dysnomia.Domain.bin
{
    public class execute : Command
    {
        new public static string Name = "execute";
        new public static string Description = "Call a contract function. Usage: [CONTRACT func arg...] or [execute CONTRACT func arg...]";

        protected override void Phi()
        {
            try {
                string contractAlias;
                string funcName;
                dynamic[] funcArgs;

                if (string.Equals(Alias, "execute", StringComparison.OrdinalIgnoreCase)) {
                    // Called directly: execute CONTRACT func [args...]
                    if (Args == null || Args.Length < 2) {
                        Logging.Log("execute", "Usage: execute CONTRACT function [args...]", 7);
                        return;
                    }
                    contractAlias = Args[0].ToString();
                    funcName      = Args[1].ToString();
                    funcArgs      = Args.Skip(2).ToArray();
                } else {
                    // Fallback: CONTRACT func [args...]
                    if (Args == null || Args.Length < 1) {
                        Logging.Log("execute", "Usage: CONTRACT function [args...]", 7);
                        return;
                    }
                    contractAlias = Alias;
                    funcName      = Args[0].ToString();
                    funcArgs      = Args.Skip(1).ToArray();
                }

                Logging.Log("execute", contractAlias + "." + funcName + "(" + string.Join(", ", funcArgs) + ")", 3);

                dynamic result = Controller.LocalContracts
                    .ExecuteWithAliases(contractAlias, funcName, funcArgs)
                    .GetAwaiter().GetResult();

                string output = result == null ? "(null)" : result.ToString();
                Command.Result = result;
                Logging.Log("execute", output, 6);

            } catch (Exception ex) {
                Logging.Log("execute", "Error: " + ex.Message, 7);
            }
        }
    }
}
