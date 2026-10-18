"""
Iteration 11 Tests: Menu Engineering AI Import, Price Adjust, What-If Advanced
Tests for new features:
1. AI Menu Import (PDF/JPEG) - POST /api/menu/ai-import
2. Bulk Price Adjustment - POST /api/menu/price-adjust
3. What-If Advanced with projectedQty - POST /api/analytics/what-if-advanced
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
OWNER_CREDS = {"email": "owner@nua.com", "password": "NuaOwner2026!"}
MANAGER_CREDS = {"email": "manager@nua.com", "password": "Staff2026!"}
CASHIER_CREDS = {"email": "cashier@nua.com", "password": "Staff2026!"}


@pytest.fixture(scope="module")
def owner_token():
    """Get owner auth token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json=OWNER_CREDS)
    assert response.status_code == 200, f"Owner login failed: {response.text}"
    return response.json().get("token")


@pytest.fixture(scope="module")
def manager_token():
    """Get manager auth token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json=MANAGER_CREDS)
    assert response.status_code == 200, f"Manager login failed: {response.text}"
    return response.json().get("token")


@pytest.fixture(scope="module")
def cashier_token():
    """Get cashier auth token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json=CASHIER_CREDS)
    assert response.status_code == 200, f"Cashier login failed: {response.text}"
    return response.json().get("token")


@pytest.fixture(scope="module")
def test_product(owner_token):
    """Create a test product for simulations"""
    headers = {"Authorization": f"Bearer {owner_token}"}
    product_data = {
        "name": f"TEST_SimProduct_{uuid.uuid4().hex[:6]}",
        "category": "Beverages",
        "price": 10.00,
        "cost": 3.50,
        "stock": 100,
        "sku": f"TEST-{uuid.uuid4().hex[:4].upper()}",
        "image": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=200",
        "gstRate": 10.0
    }
    response = requests.post(f"{BASE_URL}/api/products", json=product_data, headers=headers)
    assert response.status_code in [200, 201], f"Failed to create test product: {response.text}"
    product = response.json()
    yield product
    # Cleanup
    requests.delete(f"{BASE_URL}/api/products/{product['id']}", headers=headers)


class TestAuth:
    """Verify auth is working for all roles"""
    
    def test_owner_login(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json=OWNER_CREDS)
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["user"]["role"] == "owner"
        print("PASS: Owner login returns token and role=owner")
    
    def test_manager_login(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json=MANAGER_CREDS)
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["role"] == "manager"
        print("PASS: Manager login returns role=manager")
    
    def test_cashier_login(self):
        response = requests.post(f"{BASE_URL}/api/auth/login", json=CASHIER_CREDS)
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["role"] == "cashier"
        print("PASS: Cashier login returns role=cashier")


class TestAIMenuImport:
    """Test AI Menu Import endpoint - POST /api/menu/ai-import"""
    
    def test_ai_import_owner_access(self, owner_token):
        """Owner can reach the AI import endpoint's auth/role gate.

        "dGVzdCBtZW51IGRhdGE=" decodes to the literal text "test menu data",
        not a real image — it was never going to produce menu items. This
        used to assert an unconditional 200 ("accept it even if AI parsing
        fails"), which stopped being true once menu_features.py started
        giving honest, specific errors: 503 if OPENAI_API_KEY isn't
        configured on the server under test, 422 if it is and the payload
        is rejected as an invalid image before any provider call. Either
        is a real, correct response — only a role-check failure (401/403)
        would mean the owner couldn't even reach the endpoint.
        """
        headers = {"Authorization": f"Bearer {owner_token}"}
        data = {"fileData": "dGVzdCBtZW51IGRhdGE=", "fileType": "image"}
        response = requests.post(f"{BASE_URL}/api/menu/ai-import", json=data, headers=headers)
        assert response.status_code in (200, 422, 503), f"AI import failed: {response.text}"
        print(f"PASS: Owner can access AI import — status {response.status_code}")

    def test_ai_import_manager_access(self, manager_token):
        """Manager can reach the AI import endpoint's auth/role gate (see
        test_ai_import_owner_access for why 200/422/503 are all valid)."""
        headers = {"Authorization": f"Bearer {manager_token}"}
        data = {"fileData": "dGVzdCBtZW51IGRhdGE=", "fileType": "image"}
        response = requests.post(f"{BASE_URL}/api/menu/ai-import", json=data, headers=headers)
        assert response.status_code in (200, 422, 503), f"Manager AI import failed: {response.text}"
        print("PASS: Manager can access AI import")
    
    def test_ai_import_cashier_denied(self, cashier_token):
        """Cashier cannot access AI import endpoint"""
        headers = {"Authorization": f"Bearer {cashier_token}"}
        data = {"fileData": "dGVzdCBtZW51IGRhdGE=", "fileType": "image"}
        response = requests.post(f"{BASE_URL}/api/menu/ai-import", json=data, headers=headers)
        assert response.status_code == 403, f"Cashier should be denied: {response.status_code}"
        print("PASS: Cashier denied AI import access (403)")


class TestBulkPriceAdjust:
    """Test Bulk Price Adjustment - POST /api/menu/price-adjust"""
    
    def test_price_adjust_percentage_increase(self, owner_token, test_product):
        """Test percentage price increase"""
        headers = {"Authorization": f"Bearer {owner_token}"}
        # Get current price
        response = requests.get(f"{BASE_URL}/api/products", headers=headers)
        products = response.json()
        test_prod = next((p for p in products if p["id"] == test_product["id"]), None)
        original_price = test_prod["price"] if test_prod else test_product["price"]
        
        # Apply 10% increase to test product's category
        data = {
            "category": test_product["category"],
            "type": "percentage",
            "amount": 10,
            "direction": "increase"
        }
        response = requests.post(f"{BASE_URL}/api/menu/price-adjust", json=data, headers=headers)
        assert response.status_code == 200, f"Price adjust failed: {response.text}"
        result = response.json()
        assert "updated" in result
        assert result["updated"] > 0
        print(f"PASS: Price adjust updated {result['updated']} items by 10% increase")
        
        # Verify price changed
        response = requests.get(f"{BASE_URL}/api/products", headers=headers)
        products = response.json()
        updated_prod = next((p for p in products if p["id"] == test_product["id"]), None)
        if updated_prod:
            expected_price = round(original_price * 1.10, 2)
            assert abs(updated_prod["price"] - expected_price) < 0.02, f"Price not updated correctly: {updated_prod['price']} vs expected {expected_price}"
            print(f"PASS: Price verified - original: ${original_price}, new: ${updated_prod['price']}")
    
    def test_price_adjust_fixed_decrease(self, owner_token, test_product):
        """Test fixed amount price decrease"""
        headers = {"Authorization": f"Bearer {owner_token}"}
        data = {
            "category": test_product["category"],
            "type": "fixed",
            "amount": 0.50,
            "direction": "decrease"
        }
        response = requests.post(f"{BASE_URL}/api/menu/price-adjust", json=data, headers=headers)
        assert response.status_code == 200, f"Price adjust failed: {response.text}"
        result = response.json()
        assert "updated" in result
        print(f"PASS: Fixed decrease applied to {result['updated']} items")
    
    def test_price_adjust_all_categories(self, owner_token):
        """Test price adjust with no category (all items)"""
        headers = {"Authorization": f"Bearer {owner_token}"}
        data = {
            "category": None,  # All categories
            "type": "percentage",
            "amount": 1,  # Small 1% increase
            "direction": "increase"
        }
        response = requests.post(f"{BASE_URL}/api/menu/price-adjust", json=data, headers=headers)
        assert response.status_code == 200, f"Price adjust all failed: {response.text}"
        result = response.json()
        assert result["updated"] > 0
        print(f"PASS: All-category price adjust updated {result['updated']} items")
    
    def test_price_adjust_manager_access(self, manager_token):
        """Manager can adjust prices"""
        headers = {"Authorization": f"Bearer {manager_token}"}
        data = {"category": "Food", "type": "percentage", "amount": 0.1, "direction": "increase"}
        response = requests.post(f"{BASE_URL}/api/menu/price-adjust", json=data, headers=headers)
        assert response.status_code == 200, f"Manager price adjust failed: {response.text}"
        print("PASS: Manager can adjust prices")
    
    def test_price_adjust_cashier_denied(self, cashier_token):
        """Cashier cannot adjust prices"""
        headers = {"Authorization": f"Bearer {cashier_token}"}
        data = {"category": "Food", "type": "percentage", "amount": 5, "direction": "increase"}
        response = requests.post(f"{BASE_URL}/api/menu/price-adjust", json=data, headers=headers)
        assert response.status_code == 403, f"Cashier should be denied: {response.status_code}"
        print("PASS: Cashier denied price adjust access (403)")


class TestWhatIfAdvanced:
    """Test What-If Advanced with projectedQty - POST /api/analytics/what-if-advanced"""
    
    def test_whatif_with_projected_qty(self, owner_token, test_product):
        """Test what-if simulation with manual projected quantity"""
        headers = {"Authorization": f"Bearer {owner_token}"}
        data = {
            "changes": [{
                "productId": test_product["id"],
                "newPrice": 12.00,
                "newCost": 4.00,
                "projectedQty": 100  # Manual quantity projection
            }]
        }
        response = requests.post(f"{BASE_URL}/api/analytics/what-if-advanced", json=data, headers=headers)
        assert response.status_code == 200, f"What-if failed: {response.text}"
        result = response.json()
        
        # Verify response structure
        assert "items" in result
        assert "summary" in result
        assert len(result["items"]) == 1
        
        item = result["items"][0]
        assert item["productId"] == test_product["id"]
        assert item["projectedQty"] == 100
        assert item["newPrice"] == 12.00
        assert item["newCost"] == 4.00
        
        # Verify calculations
        expected_revenue = 12.00 * 100  # 1200
        expected_profit = (12.00 - 4.00) * 100  # 800
        assert item["projectedRevenue"] == expected_revenue
        assert item["projectedProfit"] == expected_profit
        
        print(f"PASS: What-if with projectedQty=100 - Revenue: ${item['projectedRevenue']}, Profit: ${item['projectedProfit']}")
    
    def test_whatif_without_projected_qty(self, owner_token, test_product):
        """Test what-if simulation without projected quantity (uses historical)"""
        headers = {"Authorization": f"Bearer {owner_token}"}
        data = {
            "changes": [{
                "productId": test_product["id"],
                "newPrice": 15.00,
                "newCost": 5.00,
                "projectedQty": 0  # Should fallback to historical
            }]
        }
        response = requests.post(f"{BASE_URL}/api/analytics/what-if-advanced", json=data, headers=headers)
        assert response.status_code == 200, f"What-if failed: {response.text}"
        result = response.json()
        
        assert "items" in result
        item = result["items"][0]
        # projectedQty should be calculated from historical data
        assert item["projectedQty"] >= 0
        print(f"PASS: What-if without projectedQty - calculated qty: {item['projectedQty']}")
    
    def test_whatif_multiple_products(self, owner_token, test_product):
        """Test what-if with multiple product changes"""
        headers = {"Authorization": f"Bearer {owner_token}"}
        
        # Get another product
        response = requests.get(f"{BASE_URL}/api/products", headers=headers)
        products = response.json()
        other_product = next((p for p in products if p["id"] != test_product["id"]), None)
        
        if not other_product:
            pytest.skip("Need at least 2 products for this test")
        
        data = {
            "changes": [
                {"productId": test_product["id"], "newPrice": 11.00, "newCost": 3.50, "projectedQty": 50},
                {"productId": other_product["id"], "newPrice": other_product["price"] * 1.1, "newCost": other_product.get("cost", 0), "projectedQty": 30}
            ]
        }
        response = requests.post(f"{BASE_URL}/api/analytics/what-if-advanced", json=data, headers=headers)
        assert response.status_code == 200, f"What-if failed: {response.text}"
        result = response.json()
        
        assert len(result["items"]) == 2
        assert "summary" in result
        assert "currentRevenue" in result["summary"]
        assert "projectedRevenue" in result["summary"]
        assert "profitChange" in result["summary"]
        print(f"PASS: What-if with 2 products - Summary profit change: ${result['summary']['profitChange']}")
    
    def test_whatif_manager_access(self, manager_token, test_product):
        """Manager can run what-if simulations"""
        headers = {"Authorization": f"Bearer {manager_token}"}
        data = {"changes": [{"productId": test_product["id"], "newPrice": 10.00, "newCost": 3.00, "projectedQty": 20}]}
        response = requests.post(f"{BASE_URL}/api/analytics/what-if-advanced", json=data, headers=headers)
        assert response.status_code == 200, f"Manager what-if failed: {response.text}"
        print("PASS: Manager can run what-if simulations")
    
    def test_whatif_cashier_denied(self, cashier_token, test_product):
        """Cashier cannot run what-if simulations"""
        headers = {"Authorization": f"Bearer {cashier_token}"}
        data = {"changes": [{"productId": test_product["id"], "newPrice": 10.00, "newCost": 3.00, "projectedQty": 20}]}
        response = requests.post(f"{BASE_URL}/api/analytics/what-if-advanced", json=data, headers=headers)
        assert response.status_code == 403, f"Cashier should be denied: {response.status_code}"
        print("PASS: Cashier denied what-if access (403)")


class TestMenuEngineeringPage:
    """Test Menu Engineering analytics endpoint"""
    
    def test_menu_engineering_data(self, owner_token):
        """Verify menu engineering endpoint returns proper data"""
        headers = {"Authorization": f"Bearer {owner_token}"}
        response = requests.get(f"{BASE_URL}/api/analytics/menu-engineering", headers=headers)
        assert response.status_code == 200, f"Menu engineering failed: {response.text}"
        result = response.json()
        
        assert "items" in result
        assert "categories" in result
        assert "summary" in result
        
        # Verify item structure
        if len(result["items"]) > 0:
            item = result["items"][0]
            assert "name" in item
            assert "price" in item
            assert "cost" in item
            assert "margin" in item
            assert "classification" in item  # star, puzzle, horse, dog
        
        print(f"PASS: Menu engineering returns {len(result['items'])} items, {len(result['categories'])} categories")


class TestRegressionEndpoints:
    """Regression tests for existing endpoints"""
    
    def test_products_endpoint(self, owner_token):
        """Products endpoint still works"""
        headers = {"Authorization": f"Bearer {owner_token}"}
        response = requests.get(f"{BASE_URL}/api/products", headers=headers)
        assert response.status_code == 200
        print("PASS: Products endpoint working")
    
    def test_transactions_endpoint(self, owner_token):
        """Transactions endpoint still works"""
        headers = {"Authorization": f"Bearer {owner_token}"}
        response = requests.get(f"{BASE_URL}/api/transactions", headers=headers)
        assert response.status_code == 200
        print("PASS: Transactions endpoint working")
    
    def test_customers_endpoint(self, owner_token):
        """Customers endpoint still works"""
        headers = {"Authorization": f"Bearer {owner_token}"}
        response = requests.get(f"{BASE_URL}/api/customers", headers=headers)
        assert response.status_code == 200
        print("PASS: Customers endpoint working")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
