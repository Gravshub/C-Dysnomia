// save.cs — Persist alias mappings to disk
//
// Writes all current alias→address mappings to the base config file
// (RootFolder/þ) so they survive process restarts.
//
// Usage:
//   save
//
// File format: one entry per line, delimited by the base marker:
//   ALIAS<NUL>þ<NUL>0xADDRESS
//
// This is read back automatically at startup by Contracts constructor
// if the þ base alias file exists. The install.dys script calls save
// after deploying the core contracts so the next session picks up where
// it left off without redeploying.

using Dysnomia.Lib;
using System.Text;

namespace Dysnomia.Domain.bin
{
    public class save : Command
    {
        new public static string Name = "save";
        new public static string Description = "Persist alias mappings to disk. Usage: save";

        protected override void Phi()
        {
            try {
                string rootFolder = Wallet.Contracts.RootFolder;
                if (rootFolder == null) {
                    Logging.Log("save", "RootFolder not set — cannot save", 7);
                    return;
                }

                string baseConfigFile = Path.Combine(rootFolder, Wallet.Wallet._base);
                string separator = "\0" + Wallet.Wallet._base + "\0";

                int count = 0;
                using (StreamWriter sw = new StreamWriter(baseConfigFile, append: false)) {
                    foreach (var kvp in Wallet.Aliases.Forward) {
                        sw.WriteLine(kvp.Key + separator + kvp.Value);
                        count++;
                    }
                }

                Command.Result = baseConfigFile;
                Logging.Log("save", count + " aliases saved → " + baseConfigFile, 6);

            } catch (Exception ex) {
                Logging.Log("save", "Error: " + ex.Message, 7);
            }
        }
    }
}
