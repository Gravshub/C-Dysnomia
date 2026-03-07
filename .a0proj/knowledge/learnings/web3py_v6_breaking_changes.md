# web3py_v6_breaking_changes

ContractConstructor.call() removed in web3.py v6. Build TX first, then w3.eth.call() with data field. is_connected() can false-negative — use w3.eth.block_number as fallback probe.
