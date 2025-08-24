#!/usr/bin/env python3
"""
测试租赁记录更新API
"""

import requests
import json

def test_rental_update():
    """测试更新租赁记录"""
    url = "http://localhost:5001/web/rentals/5"
    
    # 测试数据
    test_data = {
        "end_date": "2025-08-22",
        "customer_phone": "15813820179",
        "destination": "fdfsdf",
        "ship_out_tracking_no": "sf123123",
        "ship_in_tracking_no": "fd123123"
    }
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    try:
        print(f"正在测试更新租赁记录 ID: 5")
        print(f"请求数据: {json.dumps(test_data, indent=2, ensure_ascii=False)}")
        
        # 发送PUT请求
        response = requests.put(url, json=test_data, headers=headers)
        
        print(f"响应状态码: {response.status_code}")
        print(f"响应头: {dict(response.headers)}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"更新成功!")
            print(f"响应数据: {json.dumps(result, indent=2, ensure_ascii=False)}")
        else:
            print(f"更新失败!")
            try:
                error_data = response.json()
                print(f"错误信息: {json.dumps(error_data, indent=2, ensure_ascii=False)}")
            except:
                print(f"响应内容: {response.text}")
                
    except requests.exceptions.RequestException as e:
        print(f"请求异常: {e}")
    except Exception as e:
        print(f"其他异常: {e}")

def test_rental_get():
    """测试获取租赁记录"""
    url = "http://localhost:5001/web/rentals/5"
    
    try:
        print(f"\n正在获取租赁记录 ID: 5")
        
        response = requests.get(url)
        
        print(f"响应状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"获取成功!")
            print(f"租赁记录: {json.dumps(result, indent=2, ensure_ascii=False)}")
        else:
            print(f"获取失败!")
            try:
                error_data = response.json()
                print(f"错误信息: {json.dumps(error_data, indent=2, ensure_ascii=False)}")
            except:
                print(f"响应内容: {response.text}")
                
    except requests.exceptions.RequestException as e:
        print(f"请求异常: {e}")
    except Exception as e:
        print(f"其他异常: {e}")

if __name__ == "__main__":
    print("=== 租赁记录更新API测试 ===\n")
    
    # 先获取当前记录
    test_rental_get()
    
    print("\n" + "="*50 + "\n")
    
    # 测试更新
    test_rental_update()
    
    print("\n" + "="*50 + "\n")
    
    # 再次获取记录，查看是否更新成功
    test_rental_get()
