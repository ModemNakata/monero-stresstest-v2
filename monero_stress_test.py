#!/usr/bin/env python3
"""
Monero Stress Test - Network Dust Attack Simulator
Tests the network by sending many small transactions to multiple addresses
"""

import requests
import json
import time
import logging
import argparse
import sys
from typing import List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime

# Configure logging - console only
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


@dataclass
class TransferConfig:
    """Configuration for stress test"""
    wallet_rpc_url: str = "http://127.0.0.1:28088"
    rpc_user: str = ""
    rpc_password: str = ""
    
    # Transaction parameters
    dust_amount: int = 1_000_000_000  # 0.001 XMR in atomic units
    addresses_per_tx: int = 10  # Number of destinations per transaction
    num_transactions: int = 100  # Total transactions to send
    priority: int = 0  # Always 0 (lowest priority) for stress testing
    unlock_time: int = 0  # Blocks until spendable
    
    # Testing parameters
    num_recipient_addresses: int = 50  # Number of addresses to generate/use
    parallel_txs: int = 1  # Number of parallel transactions
    delay_between_tx: float = 0.5  # Seconds between transactions
    get_tx_key: bool = False  # Don't need keys for stress test
    get_tx_hex: bool = False  # Reduce response size
    
    # List of recipient addresses (populated by script)
    recipient_addresses: List[str] = None


class MoneroStressTest:
    def __init__(self, config: TransferConfig):
        self.config = config
        self.session = requests.Session()
        self.stats = {
            'total_sent': 0,
            'total_fees': 0,
            'successful_txs': 0,
            'failed_txs': 0,
            'tx_hashes': [],
            'errors': []
        }
        
    def make_rpc_call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make a JSON-RPC call to monero-wallet-rpc"""
        payload = {
            "jsonrpc": "2.0",
            "id": str(int(time.time() * 1000)),
            "method": method,
            "params": params
        }
        
        auth = None
        if self.config.rpc_user:
            auth = (self.config.rpc_user, self.config.rpc_password)
        
        try:
            response = self.session.post(
                f"{self.config.wallet_rpc_url}/json_rpc",
                json=payload,
                auth=auth,
                timeout=120
            )
            response.raise_for_status()
            
            result = response.json()
            
            # Check for RPC errors
            if "error" in result and result["error"] is not None:
                error_msg = f"RPC Error: {result['error']}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
            return result.get("result", {})
            
        except requests.RequestException as e:
            error_msg = f"Request failed: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)
    
    def get_balance(self) -> Tuple[int, int]:
        """Get wallet balance"""
        try:
            result = self.make_rpc_call("get_balance", {})
            return result.get("balance", 0), result.get("unlocked_balance", 0)
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return 0, 0
    
    def get_address(self) -> str:
        """Get primary wallet address"""
        try:
            result = self.make_rpc_call("get_address", {"account_index": 0})
            return result.get("address", "")
        except Exception as e:
            logger.error(f"Failed to get address: {e}")
            return ""
    
    def get_accounts(self) -> List[Dict[str, Any]]:
        """Get all accounts in wallet"""
        try:
            result = self.make_rpc_call("get_accounts", {})
            return result.get("subaddress_accounts", [])
        except Exception as e:
            logger.error(f"Failed to get accounts: {e}")
            return []
    
    def create_account(self, label: str = "") -> Dict[str, Any]:
        """Create a new account"""
        try:
            params = {}
            if label:
                params["label"] = label
            result = self.make_rpc_call("create_account", params)
            return result
        except Exception as e:
            logger.error(f"Failed to create account: {e}")
            return {}
    
    def create_addresses(self, account_index: int, count: int, label_prefix: str = "") -> List[str]:
        """Create multiple addresses for an account"""
        try:
            params = {
                "account_index": account_index,
                "count": count
            }
            if label_prefix:
                params["label"] = f"{label_prefix}-{account_index}"
            
            result = self.make_rpc_call("create_address", params)
            return result.get("addresses", [])
        except Exception as e:
            logger.error(f"Failed to create addresses: {e}")
            return []
    
    def get_addresses(self, account_index: int) -> List[str]:
        """Get all addresses for an account"""
        try:
            result = self.make_rpc_call("get_address", {"account_index": account_index})
            addresses = result.get("addresses", [])
            return [addr["address"] for addr in addresses]
        except Exception as e:
            logger.error(f"Failed to get addresses: {e}")
            return []
    
    def generate_recipient_addresses(self) -> bool:
        """Generate recipient addresses by creating accounts and addresses"""
        logger.info(f"Generating {self.config.num_recipient_addresses} recipient addresses...")
        
        addresses = []
        
        # Strategy: Use multiple accounts to generate many addresses
        # Create ~1 address per account for simplicity
        addresses_per_account = 1
        num_accounts_needed = (self.config.num_recipient_addresses + addresses_per_account - 1) // addresses_per_account
        
        for account_num in range(num_accounts_needed):
            if len(addresses) >= self.config.num_recipient_addresses:
                break
            
            # Create account
            logger.info(f"Creating account {account_num + 1}/{num_accounts_needed}...")
            account_label = f"stress-test-account-{account_num}"
            account_result = self.create_account(account_label)
            
            if not account_result or "account_index" not in account_result:
                logger.warning(f"Failed to create account {account_num}")
                continue
            
            account_index = account_result["account_index"]
            
            # Use the primary address of this account
            if "address" in account_result:
                addresses.append(account_result["address"])
                logger.info(f"  Account {account_index}: {account_result['address']}")
        
        # If we still need more addresses, create subaddresses
        if len(addresses) < self.config.num_recipient_addresses:
            addresses_still_needed = self.config.num_recipient_addresses - len(addresses)
            logger.info(f"Creating {addresses_still_needed} more addresses as subaddresses...")
            
            # Use account 0 for subaddresses
            new_addresses = self.create_addresses(0, addresses_still_needed, "stress-subaddr")
            addresses.extend(new_addresses)
        
        self.config.recipient_addresses = addresses[:self.config.num_recipient_addresses]
        logger.info(f"Successfully generated {len(self.config.recipient_addresses)} recipient addresses")
        return len(self.config.recipient_addresses) > 0
    
    def create_transfer(self, destinations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Send a transfer to multiple destinations"""
        params = {
            "destinations": destinations,
            "account_index": 0,
            "priority": 0,  # Always lowest priority for stress testing
            "unlock_time": self.config.unlock_time,
            "get_tx_key": self.config.get_tx_key,
            "get_tx_hex": self.config.get_tx_hex,
            "do_not_relay": False
        }
        
        return self.make_rpc_call("transfer", params)
    
    def generate_destinations(self, num_dests: int) -> List[Dict[str, Any]]:
        """Generate list of destinations with dust amounts"""
        destinations = []
        
        if not self.config.recipient_addresses:
            logger.error("No recipient addresses configured!")
            return []
        
        for i in range(num_dests):
            address = self.config.recipient_addresses[i % len(self.config.recipient_addresses)]
            destinations.append({
                "amount": self.config.dust_amount,
                "address": address
            })
        
        return destinations
    
    def send_dust_transaction(self, tx_num: int) -> bool:
        """Send a single dust transaction"""
        try:
            destinations = self.generate_destinations(self.config.addresses_per_tx)
            
            if not destinations:
                logger.error(f"Transaction {tx_num}: No destinations generated")
                self.stats['failed_txs'] += 1
                return False
            
            total_amount = sum(d["amount"] for d in destinations)
            logger.info(f"TX {tx_num}: Sending {len(destinations)} destinations, "
                       f"total amount: {total_amount / 1e12:.12f} XMR")
            
            result = self.create_transfer(destinations)
            
            # Record statistics
            tx_hash = result.get("tx_hash", "unknown")
            fee = result.get("fee", 0)
            amount = result.get("amount", 0)
            
            self.stats['successful_txs'] += 1
            self.stats['total_sent'] += amount
            self.stats['total_fees'] += fee
            self.stats['tx_hashes'].append(tx_hash)
            
            logger.info(f"TX {tx_num}: SUCCESS - Hash: {tx_hash}, "
                       f"Amount: {amount / 1e12:.12f} XMR, Fee: {fee / 1e12:.12f} XMR")
            
            return True
            
        except Exception as e:
            self.stats['failed_txs'] += 1
            error_msg = f"TX {tx_num}: FAILED - {str(e)}"
            logger.error(error_msg)
            self.stats['errors'].append(error_msg)
            return False
    
    def run_sequential(self):
        """Run stress test sequentially"""
        logger.info(f"Starting sequential stress test: {self.config.num_transactions} transactions")
        start_time = time.time()
        
        for tx_num in range(1, self.config.num_transactions + 1):
            if not self.send_dust_transaction(tx_num):
                logger.warning(f"Transaction {tx_num} failed, continuing...")
            
            if tx_num < self.config.num_transactions:
                time.sleep(self.config.delay_between_tx)
        
        elapsed = time.time() - start_time
        self.print_stats(elapsed)
    
    def run_parallel(self):
        """Run stress test with parallel transactions"""
        logger.info(f"Starting parallel stress test: {self.config.num_transactions} transactions, "
                   f"{self.config.parallel_txs} parallel workers")
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=self.config.parallel_txs) as executor:
            futures = []
            
            for tx_num in range(1, self.config.num_transactions + 1):
                future = executor.submit(self.send_dust_transaction, tx_num)
                futures.append(future)
                
                # Add delay between submissions if specified
                if self.config.delay_between_tx > 0:
                    time.sleep(self.config.delay_between_tx / self.config.parallel_txs)
            
            # Wait for all to complete
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Task failed: {e}")
        
        elapsed = time.time() - start_time
        self.print_stats(elapsed)
    
    def print_stats(self, elapsed_time: float):
        """Print final statistics"""
        logger.info("\n" + "="*70)
        logger.info("STRESS TEST COMPLETED")
        logger.info("="*70)
        logger.info(f"Duration: {elapsed_time:.2f} seconds")
        logger.info(f"Successful Transactions: {self.stats['successful_txs']}")
        logger.info(f"Failed Transactions: {self.stats['failed_txs']}")
        logger.info(f"Total XMR Sent: {self.stats['total_sent'] / 1e12:.12f}")
        logger.info(f"Total Fees Paid: {self.stats['total_fees'] / 1e12:.12f}")
        logger.info(f"Average TX/sec: {self.stats['successful_txs'] / elapsed_time:.2f}")
        
        if self.stats['successful_txs'] > 0:
            logger.info(f"Average Fee per TX: {self.stats['total_fees'] / self.stats['successful_txs'] / 1e12:.12f} XMR")
            logger.info(f"Average Amount per TX: {self.stats['total_sent'] / self.stats['successful_txs'] / 1e12:.12f} XMR")
        
        if self.stats['errors']:
            logger.info(f"\nErrors encountered: {len(self.stats['errors'])}")
            for error in self.stats['errors'][:10]:  # Show first 10 errors
                logger.info(f"  - {error}")
        
        logger.info("="*70)


def main():
    parser = argparse.ArgumentParser(
        description="Monero Stress Test - Network Dust Attack Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic stress test - generate 50 addresses and send 100 transactions
  python3 monero_stress_test.py --num-addresses 50 --transactions 100

  # High-volume parallel test
  python3 monero_stress_test.py --num-addresses 100 --transactions 1000 --parallel 5 --delay 0.1

  # Maximum spam - low dust amounts, many transactions
  python3 monero_stress_test.py --num-addresses 200 --dust 100000 \
    --transactions 500 --destinations 20

  # Custom dust amount
  python3 monero_stress_test.py --num-addresses 50 --dust 10000000 --transactions 200
        """
    )
    
    parser.add_argument("--wallet-url", type=str, default="http://127.0.0.1:28088",
                       help="Monero wallet RPC URL (default: http://127.0.0.1:28088)")
    parser.add_argument("--rpc-user", type=str, default="",
                       help="RPC username (if authentication required)")
    parser.add_argument("--rpc-password", type=str, default="",
                       help="RPC password (if authentication required)")
    
    parser.add_argument("--num-addresses", type=int, default=50,
                       help="Number of recipient addresses to generate (default: 50)")
    parser.add_argument("--dust", type=int, default=1_000_000_000,
                       help="Dust amount in atomic units (default: 1000000000 = 0.001 XMR)")
    parser.add_argument("--destinations", type=int, default=10,
                       help="Addresses per transaction (default: 10)")
    parser.add_argument("--transactions", type=int, default=100,
                       help="Total transactions to send (default: 100)")
    
    parser.add_argument("--parallel", type=int, default=1,
                       help="Number of parallel transactions (default: 1 = sequential)")
    parser.add_argument("--delay", type=float, default=0.5,
                       help="Delay between transactions in seconds (default: 0.5)")
    
    args = parser.parse_args()
    
    # Create config
    config = TransferConfig(
        wallet_rpc_url=args.wallet_url,
        rpc_user=args.rpc_user,
        rpc_password=args.rpc_password,
        dust_amount=args.dust,
        addresses_per_tx=args.destinations,
        num_transactions=args.transactions,
        num_recipient_addresses=args.num_addresses,
        parallel_txs=args.parallel,
        delay_between_tx=args.delay,
        recipient_addresses=[]
    )
    
    logger.info(f"Monero Stress Test Starting at {datetime.now()}")
    logger.info(f"Configuration:")
    logger.info(f"  Wallet RPC: {config.wallet_rpc_url}")
    logger.info(f"  Recipient addresses to generate: {config.num_recipient_addresses}")
    logger.info(f"  Dust per destination: {config.dust_amount / 1e12:.12f} XMR")
    logger.info(f"  Addresses per TX: {config.addresses_per_tx}")
    logger.info(f"  Total Transactions: {config.num_transactions}")
    logger.info(f"  Parallel Workers: {config.parallel_txs}")
    logger.info(f"  Delay between TX: {config.delay_between_tx}s")
    logger.info(f"  Priority: 0 (lowest)")
    
    # Initialize stress test
    stress_test = MoneroStressTest(config)
    
    # Check connectivity and balance
    logger.info("\nChecking wallet connectivity...")
    try:
        primary_addr = stress_test.get_address()
        balance, unlocked = stress_test.get_balance()
        
        logger.info(f"Primary Address: {primary_addr}")
        logger.info(f"Balance: {balance / 1e12:.12f} XMR")
        logger.info(f"Unlocked Balance: {unlocked / 1e12:.12f} XMR")
        
        if unlocked == 0:
            logger.error("No unlocked balance! Cannot proceed with stress test.")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to connect to wallet: {e}")
        sys.exit(1)
    
    # Generate recipient addresses
    logger.info("\n" + "="*70)
    logger.info("GENERATING RECIPIENT ADDRESSES")
    logger.info("="*70)
    
    try:
        if not stress_test.generate_recipient_addresses():
            logger.error("Failed to generate recipient addresses!")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Error generating addresses: {e}")
        sys.exit(1)
    
    logger.info(f"Generated {len(config.recipient_addresses)} addresses successfully")
    
    # Run stress test
    logger.info("\n" + "="*70)
    logger.info("STARTING STRESS TEST")
    logger.info("="*70 + "\n")
    
    if config.parallel_txs > 1:
        stress_test.run_parallel()
    else:
        stress_test.run_sequential()
    
    logger.info(f"Stress test completed at {datetime.now()}")


if __name__ == "__main__":
    main()
