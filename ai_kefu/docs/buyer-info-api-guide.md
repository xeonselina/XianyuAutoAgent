# Buyer Information API Guide

## Overview

The `get_buyer_info()` method has been added to the `XianyuProvider` interface to fetch buyer information including:
- Purchase history statistics (buy count, deal count, trade count)
- Whether the buyer has previously purchased from the current seller
- Buyer nickname and user type
- Buyer location information (if available)

## Implementation Details

### API Endpoint

- **Name**: `mtop.taobao.idlemessage.pc.user.query`
- **Version**: 4.0
- **HTTP URL**: `https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.pc.user.query/4.0/`
- **Method**: POST
- **Protocol**: Form-encoded (application/x-www-form-urlencoded)

### Request Structure

**Query Parameters:**
```python
{
    "jsv": "2.7.2",
    "appKey": "34839810",
    "t": str(int(time.time()) * 1000),  # Timestamp in milliseconds
    "sign": generate_sign(t, token, data_val),  # HMAC-SHA1 signature
    "v": "4.0",
    "type": "originaljson",
    "accountSite": "xianyu",
    "dataType": "json",
    "timeout": "20000",
    "api": "mtop.taobao.idlemessage.pc.user.query",
    "sessionOption": "AutoLoginOnly",
}
```

**Request Body (form field `data`):**
```json
{
    "type": 1,
    "userId": "<buyer_user_id>"
}
```

### Response Structure

**Success Response:**
```python
{
    "success": True,
    "buyer_id": str,              # The buyer's user ID
    "buyer_nick": str,            # Buyer's nickname
    "buy_count": int,             # Total number of items purchased
    "deal_count": int,            # Number of completed transactions
    "trade_count": int,           # Total trade count
    "has_bought": bool,           # Whether buyer has purchased from current seller
    "user_type": int,             # 1=buyer, 2=seller
    "location": str,              # Buyer's region/location (if available)
    "_raw_api_response": dict,    # Full API response for debugging
}
```

**Error Response:**
```python
{
    "success": False,
    "error": str,                 # Error message
    "raw_ret": list,              # API error codes
}
```

### Usage Examples

#### Python Implementation

```python
from ai_kefu.xianyu_provider import GoofishProvider

# Initialize provider with cookies
provider = GoofishProvider(cookies_str)

# Fetch buyer information
result = await provider.get_buyer_info(buyer_id="12345")

if result["success"]:
    print(f"Buyer: {result['buyer_nick']}")
    print(f"Previous purchases: {result['buy_count']}")
    print(f"Has bought from us: {result['has_bought']}")
    print(f"Location: {result['location']}")
else:
    print(f"Error: {result['error']}")
```

#### Integration with Order Processing

```python
async def process_buyer_order(order_id):
    # Get order details
    order = await provider.get_order_detail(order_id)
    buyer_id = order["buyer_id"]
    
    # Get buyer information
    buyer_info = await provider.get_buyer_info(buyer_id)
    
    if buyer_info["success"]:
        # Check if this is a repeat customer
        if buyer_info["has_bought"]:
            print("Repeat customer - prioritize this order!")
        
        # Estimate shipping time based on location
        location = buyer_info["location"]
        if "北京" in location:
            shipping_days = 1
        elif "远郊" in location:
            shipping_days = 3
        else:
            shipping_days = 2
            
        return {
            "order_id": order_id,
            "buyer": buyer_info,
            "estimated_shipping_days": shipping_days
        }
```

## API Response Fields Breakdown

### Purchase Statistics

These fields are extracted from the `ext.tradeStatus` JSON object in the API response:

- **buy_count**: Integer, total number of items this buyer has purchased across Xianyu
- **deal_count**: Integer, number of transactions completed
- **trade_count**: Integer, can be used for audit/verification
- **has_bought**: Boolean, specifically indicates if buyer has purchased from the **current seller** (you)

### User Information

- **buyer_nick**: The buyer's display nickname on Xianyu
- **user_type**: Type field (1=buyer, 2=seller, etc.)
- **location**: Geographical location if the API returns it; can be used for shipping estimation

## Authentication & Signing

The method uses HMAC-SHA1 signing consistent with other mtop APIs:

1. Extract token from `_m_h5_tk` cookie: `token = cookies.get('_m_h5_tk', '').split('_')[0]`
2. Create data string: `data_val = json.dumps({"type": 1, "userId": buyer_id})`
3. Generate signature: `sign = generate_sign(t, token, data_val)`
4. Include signature in query params

The `generate_sign()` function is provided by the upstream `goofish_utils` module (JavaScript-based, requires Node.js runtime via PyExecJS).

## Error Handling

The method returns `success=False` if:
- API returns non-SUCCESS status in `ret` array
- Network error occurs
- Invalid buyer_id provided
- Session/authentication expired

Always check `result["success"]` before accessing data fields.

## Performance Considerations

- Each call makes one HTTP request to Xianyu API
- Recommended to cache results for the same buyer_id within a session
- Can be called in parallel for multiple buyers using asyncio

## Files Modified

1. **xianyu_provider/base.py** - Added abstract method `get_buyer_info()`
2. **xianyu_provider/goofish_provider.py** - Added implementation:
   - `_sync_get_buyer_info()` - Synchronous implementation
   - `async get_buyer_info()` - Async wrapper

## Testing

To test the implementation:

```python
import asyncio
from ai_kefu.xianyu_provider import GoofishProvider

async def test_buyer_info():
    cookies = "your_cookies_here"  # Set valid Xianyu cookies
    provider = GoofishProvider(cookies)
    
    # Replace with a real buyer ID from your orders
    result = await provider.get_buyer_info("123456")
    print(result)

asyncio.run(test_buyer_info())
```

## Related APIs

- **mtop.taobao.idle.order.detail** (v1.0) - Get order information
- **mtop.taobao.idle.pc.detail** (v1.0) - Get product information
- **mtop.taobao.idlemessage.pc.loginuser.get** (v1.0) - Refresh authentication

## Limitations & Future Work

- Location data may not always be available in the API response
- The API may have rate limiting (not yet documented by Xianyu)
- Buyer information is only available for buyers who have interacted with the seller
- Consider implementing caching for frequently accessed buyer info

---

**Last Updated**: 2026-04-10
**Author**: AI Development Team
