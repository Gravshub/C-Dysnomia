// e2.cs — Direct contract call (read-only / view functions)
//
// Like execute, but intended for read-only (view/pure) calls where you
// want to quickly inspect contract state without sending a transaction.
// Also useful when you have the raw 0x address rather than an alias.
//
// Usage:
//   e2 CONTRACT function [args...]
//   e2 0x965B... Chat "hello"      ← raw address OK
//   e2 VOID symbol                  ← alias OK
//
// Difference from execute:
//   execute  → general purpose, handles TX + read
//   e2       → same path, but logs at lower verbosity and always returns value
//              Useful for quick reads in a session without TX noise in output.

using Dysnomia.Lib;
using System.Text;

namespace Dysnomia.Domain.bin
{
    public class e2 : Command
    {
        new public static string Name = "e2";
        new public static string Description = "Direct contract call (read-friendly). Usage: e2 CONTRACT function [args...]";

        protected override void Phi()
        {
            try {
                if (Args == null || Args.Length < 2) {
                    Logging.Log("e2", "Usage: e2 CONTRACT function [args...]", 7);
                    return;
                }

                string contractAlias = Args[0].ToString();
                string funcName      = Args[1].ToString();
                dynamic[] funcArgs   = Args.Skip(2).ToArray();

                Logging.Log("e2", contractAlias + "." + funcName + "(" + string.Join(", ", funcArgs) + ")", 3);

                dynamic result = Controller.LocalContracts
                    .ExecuteWithAliases(contractAlias, funcName, funcArgs)
                    .GetAwaiter().GetResult();

                string output = result == null ? "(null)" : result.ToString();
                Command.Result = result;
                Logging.Log("e2", "→ " + output, 6);

            } catch (Exception ex) {
                Logging.Log("e2", "Error: " + ex.Message, 7);
            }
        }
    }
}
