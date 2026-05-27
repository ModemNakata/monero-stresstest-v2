#!/usr/bin/env python3
"""
Monero XMR Spanner
Python implementation of xmrspammer for network stress testing
Creates multiple wallets, builds output trees, and continuously spams transactions
"""

import os
import json
import time
import sys
import argparse
import subprocess
import signal
import requests
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from pathlib import Path
from datetime import datetime
import threading
from concurrent.futures import ThreadPoolExecutor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class WalletConfig:
    """Configuration for a spamming wallet"""
    wallet_index: int
    wallet_dir: Path
    wallet_file: str
    monero_wallet_rpc_port: int
    rpc_process: Optional[subprocess.Popen] = None
    leaf_accounts: List[Dict] = field(default_factory=list)
    
    def __post_init__(self):
        self.wallet_dir.mkdir(parents=True, exist_ok=True)


class MoneroWalletSpammer:
    def __init__(self, monerod_rpc_port=28089, wallet_base_dir="./spammer_wallets"):
        self.monerod_rpc_port = monerod_rpc_port
        self.monerod_rpc_url = f"http://127.0.0.1:{monerod_rpc_port}/json_rpc"
        self.wallet_base_dir = Path(wallet_base_dir)
        self.wallet_base_dir.mkdir(parents=True, exist_ok=True)
        self.wallets: List[WalletConfig] = []
        self.session = requests.Session()
    
    def rpc_call(self, url, method, params=None, timeout=30):
        """Make RPC call"""
        if params is None:
            params = {}
        
        payload = {
            "jsonrpc": "2.0",
            "id": "0",
            "method": method,
            "params": params
        }
        
        try:
            response = self.session.post(url, json=payload, timeout=timeout)
            result = response.json()
            
            if "error" in result and result["error"] is not None:
                return {"error": result["error"]}
            
            return result.get("result", {})
        except Exception as e:
            return {"error": str(e)}
    
    def create_wallets(self, n_wallets, wallet_password="test"):
        """Create multiple spamming wallets"""
        logger.info(f"Creating {n_wallets} spamming wallet(s)...")
        
        next_rpc_port = 28088
        
        for wallet_idx in range(n_wallets):
            wallet_port = next_rpc_port - wallet_idx
            wallet_dir = self.wallet_base_dir / f"wallet_{wallet_idx}"
            wallet_file = wallet_dir / f"wallet_{wallet_idx}"
            
            logger.info(f"Creating wallet {wallet_idx} on port {wallet_port}...")
            
            wallet_config = WalletConfig(
                wallet_index=wallet_idx,
                wallet_dir=wallet_dir,
                wallet_file=str(wallet_file),
                monero_wallet_rpc_port=wallet_port
            )
            
            # Start monero-wallet-rpc process
            try:
                rpc_process = subprocess.Popen(
                    [
                        "monero-wallet-rpc",
                        f"--rpc-bind-port={wallet_port}",
                        "--rpc-bind-ip=127.0.0.1",
                        f"--wallet-file={wallet_file}",
                        "--disable-rpc-login",
                        f"--daemon-address=127.0.0.1:{self.monerod_rpc_port}",
                        "--testnet",
                        f"--password={wallet_password}",
                        "--log-level=0",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                
                wallet_config.rpc_process = rpc_process
                time.sleep(2)  # Wait for wallet to start
                
                logger.info(f"✅ Wallet {wallet_idx} started on port {wallet_port}")
                
            except Exception as e:
                logger.error(f"❌ Failed to start wallet {wallet_idx}: {e}")
                continue
            
            self.wallets.append(wallet_config)
        
        logger.info(f"✅ Created {len(self.wallets)} wallet(s)")
        return self.wallets
    
    def fund_wallets_command(self, amount_xmr):
        """Print funding command for user"""
        if not self.wallets:
            logger.error("No wallets to fund!")
            return
        
        total_addresses = [w.wallet_dir.name for w in self.wallets]
        
        print("\n" + "=" * 80)
        print("FUNDING COMMAND")
        print("=" * 80)
        print("\nRun this command in your funding wallet (monero-wallet-cli):\n")
        
        addresses_str = " ".join([self._get_wallet_address(w) for w in self.wallets])
        print(f"transfer priority {addresses_str} {amount_xmr} subtractfeefrom=all")
        
        print("\n⚠️  You must wait 10 blocks (~20 minutes) for the outputs to be spendable!")
        print("=" * 80 + "\n")
    
    def _get_wallet_address(self, wallet: WalletConfig) -> str:
        """Get primary address of a wallet"""
        url = f"http://127.0.0.1:{wallet.monero_wallet_rpc_port}/json_rpc"
        result = self.rpc_call(url, "get_address", {"account_index": 0})
        return result.get("address", "")
    
    def prepare_tree_leaves(self, n_outputs=15, n_tree_levels=3, fee_priority=4):
        """Create output tree to generate leaf accounts"""
        logger.info(f"Preparing tree leaves: {n_outputs} outputs, {n_tree_levels} levels...")
        
        total_leaves = n_outputs ** n_tree_levels
        logger.info(f"This will create ~{total_leaves} leaf accounts")
        
        for wallet_idx, wallet in enumerate(self.wallets):
            logger.info(f"\n📋 Wallet {wallet_idx}: Building tree...")
            
            url = f"http://127.0.0.1:{wallet.monero_wallet_rpc_port}/json_rpc"
            
            # Get primary address
            addr_result = self.rpc_call(url, "get_address", {"account_index": 0})
            primary_address = addr_result.get("address", "")
            
            if not primary_address:
                logger.error(f"❌ Could not get address for wallet {wallet_idx}")
                continue
            
            # Build tree by creating transactions
            for level in range(n_tree_levels):
                logger.info(f"  Level {level + 1}/{n_tree_levels}...")
                
                # Create destinations for this level
                destinations = []
                for i in range(n_outputs):
                    destinations.append({
                        "amount": 0,  # Use 0 to split equally
                        "address": primary_address
                    })
                
                # Send transfer_split
                params = {
                    "destinations": destinations,
                    "account_index": 0,
                    "priority": fee_priority
                }
                
                result = self.rpc_call(url, "transfer_split", params, timeout=120)
                
                if "error" in result:
                    logger.warning(f"  ⚠️  Error at level {level + 1}: {result['error']}")
                else:
                    tx_hashes = result.get("tx_hash_list", [])
                    logger.info(f"  ✅ Created {len(tx_hashes)} transaction(s)")
                
                time.sleep(2)
            
            # Get all accounts (these are the leaf accounts)
            logger.info(f"  Fetching leaf accounts...")
            accounts_result = self.rpc_call(url, "get_accounts", {})
            accounts = accounts_result.get("subaddress_accounts", [])
            
            wallet.leaf_accounts = [
                {
                    "account_index": acc.get("account_index"),
                    "label": acc.get("label", ""),
                    "base_address": acc.get("base_address", "")
                }
                for acc in accounts[1:]  # Skip primary account
            ]
            
            logger.info(f"  ✅ Found {len(wallet.leaf_accounts)} leaf accounts")
        
        logger.info("✅ Tree preparation complete!")
    
    def spam_transactions(self, fee_priority=1, delay_between_tx=0, duration_seconds=None):
        """Start spamming transactions from leaf accounts"""
        logger.info(f"Starting transaction spam (fee_priority={fee_priority}, delay={delay_between_tx}s)...")
        
        if not self.wallets:
            logger.error("No wallets available for spamming!")
            return
        
        start_time = time.time()
        
        # Use threading to run spammers in parallel
        with ThreadPoolExecutor(max_workers=len(self.wallets)) as executor:
            futures = []
            for wallet in self.wallets:
                future = executor.submit(
                    self._spam_wallet,
                    wallet,
                    fee_priority,
                    delay_between_tx,
                    start_time,
                    duration_seconds
                )
                futures.append(future)
            
            # Wait for all to complete (or until KeyboardInterrupt)
            try:
                for future in futures:
                    future.result()
            except KeyboardInterrupt:
                logger.info("\n⏹️  Stopping spam...")
    
    def _spam_wallet(self, wallet: WalletConfig, fee_priority, delay_between_tx, start_time, duration_seconds):
        """Spam transactions for a single wallet"""
        url = f"http://127.0.0.1:{wallet.monero_wallet_rpc_port}/json_rpc"
        log_file = wallet.wallet_dir / "spam.log"
        
        logger.info(f"🚀 Wallet {wallet.wallet_index}: Starting spam loop with {len(wallet.leaf_accounts)} leaf accounts")
        
        row_iter = 0
        tx_count = 0
        
        try:
            while True:
                # Check if duration exceeded
                if duration_seconds and (time.time() - start_time) > duration_seconds:
                    logger.info(f"Wallet {wallet.wallet_index}: Duration exceeded, stopping")
                    break
                
                leaf = wallet.leaf_accounts[row_iter]
                account_index = leaf["account_index"]
                label = leaf["label"]
                address = leaf["base_address"]
                
                # Sweep all from this account
                params = {
                    "address": address,
                    "account_index": account_index,
                    "priority": fee_priority
                }
                
                result = self.rpc_call(url, "sweep_all", params)
                
                if "error" in result:
                    log_msg = f"{datetime.now()} Account {label}: Error - {result['error']}"
                else:
                    tx_hashes = result.get("tx_hash_list", [])
                    amounts = result.get("amount_list", [])
                    fees = result.get("fee_list", [])
                    
                    if tx_hashes:
                        tx_count += len(tx_hashes)
                        amount_xmr = sum(amounts) / 1e12
                        fee_xmr = sum(fees) / 1e12
                        tx_hash = tx_hashes[0]
                        
                        log_msg = (f"{datetime.now()} Account {label}: "
                                 f"Amount={amount_xmr:.8f} XMR, Fee={fee_xmr:.8f} XMR, "
                                 f"Hash={tx_hash}")
                    else:
                        log_msg = f"{datetime.now()} Account {label}: No transactions"
                
                # Write to log
                try:
                    with open(log_file, "a") as f:
                        f.write(log_msg + "\n")
                except:
                    pass
                
                # Print progress every 100 transactions
                if tx_count % 100 == 0 and tx_count > 0:
                    logger.info(f"Wallet {wallet.wallet_index}: {tx_count} transactions sent")
                
                # Move to next leaf account
                row_iter += 1
                if row_iter >= len(wallet.leaf_accounts):
                    row_iter = 0
                
                # Add delays for long iterations
                key_images_len = len(result.get("spent_key_images_list", [{}])[0].get("key_images", []))
                if key_images_len > 1:
                    time.sleep(1)
                
                if tx_count % 20 == 0 and tx_count > 0:
                    time.sleep(20)  # Give time for block propagation
                
                if tx_count % 2000 == 0 and tx_count > 0:
                    time.sleep(30)  # Longer delay every 2000 transactions
                
                time.sleep(delay_between_tx)
        
        except KeyboardInterrupt:
            logger.info(f"Wallet {wallet.wallet_index}: Interrupted")
        except Exception as e:
            logger.error(f"Wallet {wallet.wallet_index}: Error - {e}")
    
    def stop_wallets(self):
        """Stop all wallet RPC processes"""
        logger.info("Stopping wallet processes...")
        
        for wallet in self.wallets:
            if wallet.rpc_process:
                try:
                    wallet.rpc_process.terminate()
                    wallet.rpc_process.wait(timeout=5)
                    logger.info(f"Wallet {wallet.wallet_index}: Stopped")
                except:
                    wallet.rpc_process.kill()


def main():
    parser = argparse.ArgumentParser(
        description="Monero XMR Spanner - Network stress testing tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow:
  1. Create wallets:        python3 xmr_spanner.py --create --num-wallets 5
  2. Fund wallets:          (User funds manually via monero-wallet-cli)
  3. Prepare tree:          python3 xmr_spanner.py --prepare-tree --num-outputs 15 --levels 3
  4. Start spamming:        python3 xmr_spanner.py --spam --fee-priority 1
  5. Stop (Ctrl+C):         Press Ctrl+C to stop
        """
    )
    
    parser.add_argument("--monerod-port", type=int, default=28089,
                       help="Monerod RPC port (default: 28089)")
    parser.add_argument("--wallet-dir", type=str, default="./spammer_wallets",
                       help="Base directory for wallets (default: ./spammer_wallets)")
    
    parser.add_argument("--create", action="store_true",
                       help="Create wallets")
    parser.add_argument("--num-wallets", type=int, default=1,
                       help="Number of wallets to create (default: 1)")
    parser.add_argument("--fund-amount", type=float, default=30,
                       help="Amount to fund each wallet (in XMR, default: 30)")
    
    parser.add_argument("--prepare-tree", action="store_true",
                       help="Prepare tree leaves")
    parser.add_argument("--num-outputs", type=int, default=15,
                       help="Outputs per transaction level (default: 15)")
    parser.add_argument("--levels", type=int, default=3,
                       help="Number of tree levels (default: 3)")
    parser.add_argument("--tree-fee-priority", type=int, default=4,
                       help="Fee priority for tree building (default: 4)")
    
    parser.add_argument("--spam", action="store_true",
                       help="Start spamming transactions")
    parser.add_argument("--spam-fee-priority", type=int, default=1,
                       help="Fee priority for spam (default: 1)")
    parser.add_argument("--spam-delay", type=float, default=0,
                       help="Delay between transactions (default: 0)")
    parser.add_argument("--spam-duration", type=int, default=None,
                       help="Duration for spamming (seconds, default: infinite)")
    
    args = parser.parse_args()
    
    spammer = MoneroWalletSpammer(
        monerod_rpc_port=args.monerod_port,
        wallet_base_dir=args.wallet_dir
    )
    
    try:
        if args.create:
            spammer.create_wallets(args.num_wallets)
            spammer.fund_wallets_command(args.fund_amount)
        
        if args.prepare_tree:
            spammer.prepare_tree_leaves(
                n_outputs=args.num_outputs,
                n_tree_levels=args.levels,
                fee_priority=args.tree_fee_priority
            )
        
        if args.spam:
            spammer.spam_transactions(
                fee_priority=args.spam_fee_priority,
                delay_between_tx=args.spam_delay,
                duration_seconds=args.spam_duration
            )
    
    except KeyboardInterrupt:
        logger.info("\n⏹️  Interrupted by user")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        spammer.stop_wallets()


if __name__ == "__main__":
    main()
