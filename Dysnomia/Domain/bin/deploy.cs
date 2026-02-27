// deploy.cs — Deploy a Solidity contract or run a .dys script
//
// Usage:
//   deploy dysnomia/10_void.sol [constructor args...]
//   deploy install.dys              ← runs each line as a command (script mode)
//
// .sol files:
//   Compiles with solc (already installed at DYSNOMIA_SOLC path),
//   deploys to PulseChain via the current wallet account,
//   stores the deployed address as an alias keyed by the contract's symbol().
//
// .dys files (script mode):
//   Each line in the file is fed through ProcessString as a command.
//   Used for multi-step installs (see scripts/install.dys).
//
// Constructor args use alias resolution — you can pass alias names like
// "VMRNG" and they will be resolved to their 0x addresses automatically.

using Dysnomia.Lib;
using System.Text;

namespace Dysnomia.Domain.bin
{
    public class deploy : Command
    {
        new public static string Name = "deploy";
        new public static string Description = "Deploy .sol contract or run .dys script. Usage: deploy FILE [args...]";

        protected override void Phi()
        {
            try {
                if (Args == null || Args.Length < 1) {
                    Logging.Log("deploy", "Usage: deploy FILE.sol [constructor args...]", 7);
                    return;
                }

                string file = Args[0].ToString();
                dynamic[] constructorArgs = Args.Skip(1).ToArray();

                Logging.Log("deploy", "Deploying: " + file, 6);

                // Output callback that routes to the shared Logging system
                Wallet.Contracts.OutputCallback outputCb = (from, data, priority) =>
                    Logging.Log("deploy", Encoding.Default.GetString(data), priority);

                string address = Controller.LocalContracts
                    .Deploy(outputCb, file, constructorArgs)
                    .GetAwaiter().GetResult();

                if (address != null) {
                    Command.Result = address;
                    Logging.Log("deploy", "Deployed → " + address, 6);
                } else {
                    // .dys script mode — no address returned
                    Command.Result = null;
                    Logging.Log("deploy", "Script complete: " + file, 6);
                }

            } catch (Exception ex) {
                Logging.Log("deploy", "Error: " + ex.Message, 7);
            }
        }
    }
}
