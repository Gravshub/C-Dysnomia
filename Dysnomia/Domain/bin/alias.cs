// alias.cs — Add or look up alias mappings in memory
//
// Usage:
//   alias NAME 0xADDRESS    → register NAME → 0xADDRESS in the alias table
//   alias NAME              → look up NAME, print its address
//
// Aliases are in-memory for the session unless you call `save` afterwards.
// The execute and e2 commands resolve aliases automatically before calling,
// so after `alias VOID 0x965B...` you can type `VOID Chat "hello"` directly.
//
// Run `save` after adding aliases you want to persist across restarts.

using Dysnomia.Lib;
using System.Text;

namespace Dysnomia.Domain.bin
{
    public class alias : Command
    {
        new public static string Name = "alias";
        new public static string Description = "Add or look up alias. Usage: alias NAME [0xADDRESS]";

        protected override void Phi()
        {
            try {
                if (Args == null || Args.Length < 1) {
                    Logging.Log("alias", "Usage: alias NAME [0xADDRESS]", 7);
                    return;
                }

                string name = Args[0].ToString();

                if (Args.Length >= 2) {
                    // Set mode
                    string address = Args[1].ToString();
                    Wallet.Aliases.AddAlias(name, address);
                    Command.Result = address;
                    Logging.Log("alias", name + " → " + address, 6);
                } else {
                    // Look up mode
                    if (Wallet.Aliases.Forward.ContainsKey(name)) {
                        string found = Wallet.Aliases.Forward[name];
                        Command.Result = found;
                        Logging.Log("alias", name + " = " + found, 6);
                    } else {
                        Command.Result = null;
                        Logging.Log("alias", name + " not found", 6);
                    }
                }

            } catch (Exception ex) {
                Logging.Log("alias", "Error: " + ex.Message, 7);
            }
        }
    }
}
