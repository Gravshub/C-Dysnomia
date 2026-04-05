#!/usr/bin/env python3
"""Compile FloorHarvestModule.sol via solcx (standard JSON, viaIR enabled)."""
import json
import os
import solcx

solcx.set_solc_version("0.8.21")

SOL_PATH = os.path.join(os.path.dirname(__file__), "..", "contracts", "FloorHarvestModule.sol")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "build", "FloorHarvestModule")

with open(SOL_PATH, "r") as f:
    source = f.read()

input_data = {
    "language": "Solidity",
    "sources": {
        "FloorHarvestModule.sol": {
            "content": source,
        }
    },
    "settings": {
        "viaIR": True,
        "optimizer": {
            "enabled": True,
            "runs": 200,
        },
        "outputSelection": {
            "*": {
                "FloorHarvestModule": ["abi", "evm.bytecode.object"],
            }
        },
    },
}

result = solcx.compile_standard(input_data, solc_version="0.8.21")

# Check for errors
errors = result.get("errors", [])
fatal = [e for e in errors if e.get("severity") == "error"]
if fatal:
    for e in fatal:
        print(f"ERROR: {e.get('formattedMessage', e)}")
    raise RuntimeError("Compilation failed with errors")

# Warn on non-fatal
for e in errors:
    if e.get("severity") != "error":
        print(f"WARNING: {e.get('formattedMessage', e)}")

contracts = result.get("contracts", {})
file_contracts = contracts.get("FloorHarvestModule.sol", {})
contract_data = file_contracts.get("FloorHarvestModule")

if not contract_data:
    raise RuntimeError(
        f"FloorHarvestModule not found in output. Available: {list(file_contracts.keys())}"
    )

abi = contract_data["abi"]
bytecode = contract_data["evm"]["bytecode"]["object"]

os.makedirs(OUT_DIR, exist_ok=True)
out_path = os.path.join(OUT_DIR, "combined.json")
with open(out_path, "w") as f:
    json.dump({"abi": abi, "bin": bytecode}, f, indent=2)

print(f"Compiled FloorHarvestModule → {out_path}")
print(f"  ABI: {len(abi)} entries")
print(f"  Bytecode: {len(bytecode)} chars")
