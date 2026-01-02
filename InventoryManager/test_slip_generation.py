#!/usr/bin/env python3
"""
测试发货单图像生成
"""
import sys
from app import create_app, db
from app.models import Rental
from app.services.printing.shipping_slip_image_service import shipping_slip_image_service

def test_slip_generation():
    """测试发货单生成功能"""
    app = create_app()

    with app.app_context():
        # 获取第一个租赁记录用于测试
        rental = Rental.query.filter(Rental.id == 919).first()

        if not rental:
            print("❌ 数据库中没有租赁记录")
            return False

        print(f"✅ 找到租赁记录 ID: {rental.id}")
        print(f"   客户: {rental.customer_name}")
        print(f"   电话: {rental.customer_phone}")
        print(f"   地址: {rental.destination}")

        if rental.device:
            print(f"   设备: {rental.device.name}")
            print(f"   序列号: {rental.device.serial_number}")

        print("\n正在生成发货单图像...")

        try:
            # 生成图像
            image_base64 = shipping_slip_image_service.generate_slip_image(rental.id)

            print(f"✅ 发货单图像生成成功!")
            print(f"   Base64长度: {len(image_base64)} 字符")
            print(f"   估计图像大小: {len(image_base64) * 3 / 4 / 1024:.1f} KB")

            # 保存到文件查看
            import base64
            image_data = base64.b64decode(image_base64)
            with open('/tmp/test_slip.png', 'wb') as f:
                f.write(image_data)
            print(f"   已保存到: /tmp/test_slip.png")

            return True

        except Exception as e:
            print(f"❌ 发货单生成失败: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == '__main__':
    success = test_slip_generation()
    sys.exit(0 if success else 1)
