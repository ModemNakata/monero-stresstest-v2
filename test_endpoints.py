#!/usr/bin/env python3
"""
Monero RPC Endpoint Tester
Tests which endpoints are available on the wallet RPC
Run with your actual wallet RPC running to see available methods
"""

import requests
import json
import sys

def test_endpoint(url, method, params=None):
    """Test a single endpoint"""
    if params is None:
        params = {}
    
    payload = {
        "jsonrpc": "2.0",
        "id": "0",
        "method": method,
        "params": params
    }
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        result = response.json()
        
        if "error" in result and result["error"] is not None:
            error_code = result["error"].get("code", "?")
            error_msg = result["error"].get("message", "Unknown error")
            
            # -32601 = Method not found
            if error_code == -32601:
                return "❌ Method not found"
            return f"⚠️  Error {error_code}: {error_msg}"
        
        if "result" in result:
            result_keys = list(result["result"].keys()) if isinstance(result["result"], dict) else str(type(result["result"]))
            return f"✅ OK"
        
        return f"❓ Unexpected response"
    except requests.exceptions.ConnectionError:
        return "❌ Connection refused"
    except Exception as e:
        return f"❌ {str(e)[:40]}"

def main():
    print("Monero Wallet RPC Endpoint Tester\n")
    
    # Try the correct port
    wallet_url = "http://127.0.0.1:28088/json_rpc"
    
    print(f"Testing: {wallet_url}\n")
    
    # Common Monero Wallet RPC methods
    endpoints = [
        # Wallet info
        ("get_balance", {}),
        ("getbalance", {}),
        ("get_address", {"account_index": 0}),
        ("getaddress", {"account_index": 0}),
        ("get_accounts", {}),
        ("getaccounts", {}),
        ("get_height", {}),
        ("getheight", {}),
        
        # Account/Address creation
        ("create_account", {"label": "test"}),
        ("create_address", {"account_index": 0, "count": 1}),
        
        # Transfer
        ("transfer", {
            "destinations": [{"amount": 1000000000, "address": "test"}],
            "account_index": 0
        }),
        
        # Server
        ("get_version", {}),
        ("getversion", {}),
    ]
    
    print("Testing JSON-RPC methods:")
    print("-" * 70)
    
    working_methods = []
    broken_methods = []
    notfound_methods = []
    
    for method, params in endpoints:
        result = test_endpoint(wallet_url, method, params)
        status = "✅" if "✅" in result else "❌"
        print(f"{method:25} {result}")
        
        if "✅" in result:
            working_methods.append(method)
        elif "Method not found" in result:
            notfound_methods.append(method)
        else:
            broken_methods.append(method)
    
    print("\n" + "=" * 70)
    print("SUMMARY:")
    print(f"  ✅ Working methods: {len(working_methods)}")
    if working_methods:
        print(f"     {', '.join(working_methods)}")
    
    print(f"  ❌ Methods not found: {len(notfound_methods)}")
    if notfound_methods:
        print(f"     {', '.join(notfound_methods)}")
    
    print(f"  ⚠️  Other errors: {len(broken_methods)}")
    if broken_methods:
        print(f"     {', '.join(broken_methods)}")
    
    print("\n" + "=" * 70)
    print("Try updating the main script to use the working methods above")

if __name__ == "__main__":
    main()
