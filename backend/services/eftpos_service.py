"""EFTPOS Integration Service for NUA POS

Four providers actually have a class and a wire protocol below — Linkly,
Tyro and Smartpay over a raw TCP socket, Windcave via an attempted
HTTPS API call — plus SimulatorProvider, a deterministic fake terminal for
testing without real hardware or a vendor account. None of the four real
providers' protocols have been verified against each vendor's actual
certified spec (no hardware/account was available to test against); see
docs/platform/PAYMENT_TERMINAL_ARCHITECTURE.md for what that leaves as
remaining work. Westpac Presto, ANZ Worldline, NAB Transact, CBA Albert
and Square Terminal are NOT implemented — no class, no entry in
EFTPOSService.PROVIDERS — despite an earlier version of this docstring
listing them. These are partial, unverified adapters, not certified terminal
support: the four non-simulator classes inherit refund/cancel/settlement
methods that raise NotImplementedError, and Tyro/Smartpay/Windcave also
inherit the unimplemented disconnect method. Merely registering another
class does not establish support.
"""

import socket
import json
import asyncio
import uuid
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

class EFTPOSProvider:
    """Base class for EFTPOS providers"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.provider = config.get('provider')
        self.terminal_id = config.get('terminalId')
        self.connection_type = config.get('connectionType')

    async def _blocking(self, fn, *args):
        """Run a blocking call (socket connect/send/recv) off the event loop.

        Every socket-based provider below calls plain `socket.connect`,
        `.sendall` and `.recv` directly inside an `async def`. Those are
        synchronous, blocking calls — running one inline blocks this
        process's *entire* event loop, meaning every other request the
        backend is serving (every till, every kitchen display) stalls for
        however long the terminal takes to answer. A 60-second EFTPOS
        timeout would mean 60 seconds of the whole venue's POS freezing, not
        just the one payment. Routing it through the default executor keeps
        it off the loop.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn, *args)

    async def connect(self) -> bool:
        """Establish connection to EFTPOS terminal"""
        raise NotImplementedError
        
    async def disconnect(self) -> bool:
        """Close connection to EFTPOS terminal"""
        raise NotImplementedError
        
    async def purchase(self, amount: float, reference: str, cashout: float = 0.0) -> Dict[str, Any]:
        """Process purchase transaction"""
        raise NotImplementedError
        
    async def refund(self, amount: float, reference: str) -> Dict[str, Any]:
        """Process refund transaction"""
        raise NotImplementedError
        
    async def cancel(self) -> Dict[str, Any]:
        """Cancel current transaction"""
        raise NotImplementedError
        
    async def settlement(self) -> Dict[str, Any]:
        """Perform end-of-day settlement"""
        raise NotImplementedError
        
    async def status(self) -> Dict[str, Any]:
        """Get terminal status"""
        raise NotImplementedError


class LinklyProvider(EFTPOSProvider):
    """Linkly (PC-EFTPOS) Integration
    
    Most widely used EFTPOS middleware in Australia.
    Supports 700+ POS systems and most terminals.
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.socket = None
        
    async def connect(self) -> bool:
        try:
            # TCP connection to Linkly middleware
            ip = self.config.get('ipAddress', '127.0.0.1')
            port = self.config.get('port', 2011)  # Default Linkly port
            
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.config.get('timeout', 60))
            await self._blocking(self.socket.connect, (ip, port))

            logger.info(f"Connected to Linkly at {ip}:{port}")
            return True
        except Exception as e:
            logger.error(f"Linkly connection failed: {e}")
            return False
    
    async def disconnect(self) -> bool:
        if self.socket:
            self.socket.close()
        return True
    
    async def purchase(self, amount: float, reference: str, cashout: float = 0.0) -> Dict[str, Any]:
        """Linkly purchase transaction"""
        try:
            # Linkly message format
            message = {
                "MessageType": "Transaction",
                "TransactionType": "Purchase",
                "Amount": int(amount * 100),  # Convert to cents
                "CashOut": int(cashout * 100),
                "Reference": reference,
                "MerchantId": self.config.get('merchantId'),
                "TerminalId": self.terminal_id
            }
            
            # Send to Linkly
            request = json.dumps(message) + "\n"
            await self._blocking(self.socket.sendall, request.encode())

            # Receive response
            response_bytes = await self._blocking(self.socket.recv, 4096)
            result = json.loads(response_bytes.decode())
            
            return {
                "approved": result.get("Success", False),
                "responseCode": result.get("ResponseCode", "99"),
                "responseText": result.get("ResponseText", "Unknown"),
                "authCode": result.get("AuthCode"),
                "rrn": result.get("RRN"),
                "cardType": result.get("CardType"),
                "maskedPan": result.get("MaskedPAN"),
                "stan": result.get("STAN")
            }
        except Exception as e:
            logger.error(f"Linkly purchase failed: {e}")
            return {
                "approved": False,
                "responseCode": "99",
                "responseText": str(e)
            }


class TyroProvider(EFTPOSProvider):
    """Tyro EFTPOS Integration
    
    Direct integration with Tyro terminals.
    Fee-free integration.
    """
    
    async def connect(self) -> bool:
        # Tyro uses direct IP connection
        try:
            ip = self.config.get('ipAddress')
            port = self.config.get('port', 6001)  # Default Tyro port
            
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            await self._blocking(self.socket.connect, (ip, port))
            return True
        except Exception as e:
            logger.error(f"Tyro connection failed: {e}")
            return False

    async def purchase(self, amount: float, reference: str, cashout: float = 0.0) -> Dict[str, Any]:
        """Tyro purchase transaction"""
        # Tyro proprietary protocol
        try:
            message = f"T|{int(amount * 100)}|{reference}\n"
            await self._blocking(self.socket.sendall, message.encode())

            response_bytes = await self._blocking(self.socket.recv, 1024)
            parts = response_bytes.decode().split('|')
            
            return {
                "approved": parts[0] == 'A',
                "responseCode": parts[1] if len(parts) > 1 else "99",
                "responseText": parts[2] if len(parts) > 2 else "Unknown",
                "authCode": parts[3] if len(parts) > 3 else None
            }
        except Exception as e:
            logger.error(f"Tyro purchase failed: {e}")
            return {"approved": False, "responseCode": "99", "responseText": str(e)}


class SmartpayProvider(EFTPOSProvider):
    """Smartpay EFTPOS Integration
    
    Network-based integration.
    Requires Smart Link software.
    """
    
    async def connect(self) -> bool:
        try:
            ip = self.config.get('ipAddress')
            port = self.config.get('port', 6050)  # Smartpay default
            
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            await self._blocking(self.socket.connect, (ip, port))
            return True
        except Exception as e:
            logger.error(f"Smartpay connection failed: {e}")
            return False

    async def purchase(self, amount: float, reference: str, cashout: float = 0.0) -> Dict[str, Any]:
        """Smartpay purchase transaction"""
        try:
            # Smartpay XML format
            message = f'<Transaction><Type>Purchase</Type><Amount>{int(amount * 100)}</Amount><Ref>{reference}</Ref></Transaction>'
            await self._blocking(self.socket.sendall, message.encode())

            response_bytes = await self._blocking(self.socket.recv, 2048)
            response = response_bytes.decode()
            # Parse XML response
            # Simplified - real implementation needs XML parsing
            
            return {
                "approved": "Approved" in response,
                "responseCode": "00" if "Approved" in response else "99",
                "responseText": "Approved" if "Approved" in response else "Declined"
            }
        except Exception as e:
            logger.error(f"Smartpay purchase failed: {e}")
            return {"approved": False, "responseCode": "99", "responseText": str(e)}


class WindcaveProvider(EFTPOSProvider):
    """Windcave (Payment Express) Integration"""
    
    async def connect(self) -> bool:
        # Cloud-based API
        return True
    
    async def purchase(self, amount: float, reference: str, cashout: float = 0.0) -> Dict[str, Any]:
        """Windcave API purchase"""
        import requests
        
        try:
            url = self.config.get('cloudEndpoint', 'https://sec.windcave.com/api/v1/transactions')
            headers = {
                'Authorization': f"Bearer {self.config.get('apiKey')}",
                'Content-Type': 'application/json'
            }
            
            payload = {
                "type": "Purchase",
                "amount": amount,
                "currency": "AUD",
                "merchantReference": reference
            }
            
            response = await self._blocking(
                lambda: requests.post(url, json=payload, headers=headers, timeout=60))
            result = response.json()
            
            return {
                "approved": result.get('success', False),
                "responseCode": result.get('responseCode', '99'),
                "responseText": result.get('responseText', 'Unknown'),
                "authCode": result.get('authCode')
            }
        except Exception as e:
            logger.error(f"Windcave purchase failed: {e}")
            return {"approved": False, "responseCode": "99", "responseText": str(e)}


class SimulatorProvider(EFTPOSProvider):
    """A terminal that isn't there.

    Every provider above needs real hardware or a real vendor account to
    exercise even once — there was no way to test a purchase, a decline, a
    refund, a cancel, or a settlement without either. This is the "test
    terminal" a venue can configure the exact same way as a real one
    (provider: "simulator" in EFTPOSConfig) and get deterministic, documented
    behaviour instead of a live socket.

    Test-amount conventions, matching what real terminal simulators use so
    the numbers are recognisable rather than invented:
      $1.00  -> declined, insufficient funds (the most common real decline)
      $2.00  -> declined, card expired
      $3.00  -> times out / connection failure (tests the offline path)
      $4.00  -> declined, do not honour (a generic bank-side refusal)
      anything else -> approved
    Refunds and cancels always succeed against a reference this simulator
    itself issued; an unknown reference is refused, the same as a real
    terminal would refuse to refund a transaction it never processed.
    """

    DECLINE_RULES = {
        100: ("51", "Insufficient Funds"),
        200: ("54", "Expired Card"),
        400: ("05", "Do Not Honour"),
    }
    TIMEOUT_CENTS = 300

    # EFTPOSService.get_provider() builds a brand-new provider instance for
    # every single call (see process_transaction below) — nothing about this
    # object survives between a purchase and the refund that follows it. A
    # per-instance ledger would make refund() unable to ever find the
    # purchase it's meant to reverse. Keyed by terminal so two configured
    # simulator terminals don't share state, this dict lives at module scope
    # instead, alongside every other instance of this class.
    _ledgers: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._ledger = self._ledgers.setdefault(self.terminal_id or "default", {})

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> bool:
        return True

    async def status(self) -> Dict[str, Any]:
        return {"connected": True, "provider": "simulator", "terminalId": self.terminal_id}

    def _rrn(self) -> str:
        return uuid.uuid4().hex[:12].upper()

    async def purchase(self, amount: float, reference: str, cashout: float = 0.0) -> Dict[str, Any]:
        cents = int(round(amount * 100))
        rrn = self._rrn()
        stan = str(len(self._ledger) + 1).zfill(6)

        if cents == self.TIMEOUT_CENTS:
            return {"approved": False, "responseCode": "68", "responseText": "Timed out — no response from terminal"}

        decline = self.DECLINE_RULES.get(cents)
        if decline:
            code, text = decline
            self._ledger[rrn] = {"amount": amount, "reference": reference, "approved": False}
            return {"approved": False, "responseCode": code, "responseText": text, "rrn": rrn, "stan": stan}

        result = {
            "approved": True, "responseCode": "00", "responseText": "Approved",
            "authCode": uuid.uuid4().hex[:6].upper(), "rrn": rrn, "stan": stan,
            "cardType": "visa", "maskedPan": "************4242",
        }
        self._ledger[rrn] = {"amount": amount, "reference": reference, "approved": True}
        return result

    async def refund(self, amount: float, reference: str) -> Dict[str, Any]:
        original = next((v for v in self._ledger.values()
                         if v["reference"] == reference and v["approved"]), None)
        if not original:
            return {"approved": False, "responseCode": "78", "responseText": "No matching original transaction"}
        if amount > original["amount"] + 0.001:
            return {"approved": False, "responseCode": "77",
                    "responseText": f"Refund ${amount:.2f} exceeds original ${original['amount']:.2f}"}
        rrn = self._rrn()
        return {"approved": True, "responseCode": "00", "responseText": "Refund approved",
               "authCode": uuid.uuid4().hex[:6].upper(), "rrn": rrn}

    async def cancel(self) -> Dict[str, Any]:
        return {"approved": True, "responseCode": "00", "responseText": "Transaction cancelled"}

    async def settlement(self) -> Dict[str, Any]:
        approved = [v for v in self._ledger.values() if v["approved"]]
        return {
            "approved": True, "responseCode": "00", "responseText": "Settlement complete",
            "totalCount": len(approved),
            "totalAmount": round(sum(v["amount"] for v in approved), 2),
        }


class EFTPOSService:
    """Main EFTPOS service - handles all providers"""

    PROVIDERS = {
        'linkly': LinklyProvider,
        'tyro': TyroProvider,
        'smartpay': SmartpayProvider,
        'windcave': WindcaveProvider,
        'simulator': SimulatorProvider,
        # Add more providers as needed
    }
    
    def __init__(self):
        self.connections = {}
    
    def get_provider(self, config: Dict[str, Any]) -> EFTPOSProvider:
        """Get provider instance"""
        provider_type = config.get('provider', '').lower()
        provider_class = self.PROVIDERS.get(provider_type)
        
        if not provider_class:
            raise ValueError(f"Unsupported EFTPOS provider: {provider_type}")
        
        return provider_class(config)
    
    async def process_transaction(self, config: Dict[str, Any], transaction_type: str, 
                                 amount: float, reference: str, cashout: float = 0.0) -> Dict[str, Any]:
        """Process EFTPOS transaction"""
        try:
            provider = self.get_provider(config)
            
            # Connect
            connected = await provider.connect()
            if not connected:
                return {"approved": False, "responseCode": "99", "responseText": "Connection failed"}
            
            # Process transaction
            if transaction_type == 'purchase':
                result = await provider.purchase(amount, reference, cashout)
            elif transaction_type == 'refund':
                result = await provider.refund(amount, reference)
            elif transaction_type == 'cancel':
                result = await provider.cancel()
            else:
                result = {"approved": False, "responseCode": "99", "responseText": "Invalid transaction type"}
            
            # Disconnect
            await provider.disconnect()
            
            return result
            
        except Exception as e:
            logger.error(f"EFTPOS transaction failed: {e}")
            return {"approved": False, "responseCode": "99", "responseText": str(e)}

# Global service instance
eftpos_service = EFTPOSService()
