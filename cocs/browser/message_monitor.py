import asyncio
import time
from typing import Dict, List, Optional, Callable
from loguru import logger
from .dom_parser import GoofishDOMParser
from .data_persistence import DataPersistence


class MessageMonitor:
    """消息监控器 - 负责监控和处理新消息"""

    def __init__(self, page_manager, data_persistence: DataPersistence):
        self.page_manager = page_manager
        self.data_persistence = data_persistence
        self.is_running = False
        self.message_callback: Optional[Callable] = None

    async def monitor_new_messages(self, callback: Callable[[Dict], None]):
        """监控新消息 - 使用持久化存储和新消息标记串行处理"""
        self.message_callback = callback

        logger.info("📱 ===== 开始监控新消息 =====")
        logger.info("📋 使用持久化存储和串行处理模式")

        monitor_start_time = time.time()
        message_count = 0
        error_count = 0

        self.is_running = True

        while self.is_running:
            try:
                cycle_start_time = time.time()

                # 周期性状态报告
                if message_count % 50 == 0 and message_count > 0:
                    elapsed = time.time() - monitor_start_time
                    logger.info(f"📊 监控状态报告: 运行{elapsed/60:.1f}分钟, 处理{message_count}条消息, 错误{error_count}次")

                # 等待下一条新消息
                logger.debug("🔍 等待下一条新消息...")
                new_message = await self._wait_for_next_new_message()

                if new_message:
                    message_count += 1
                    wait_time = time.time() - cycle_start_time

                    logger.info(f"📨 [{message_count}] 检测到新消息 (等待耗时: {wait_time:.1f}秒)")
                    logger.info(f"📝 消息内容: {new_message.get('text', '')[:50]}...")
                    logger.info(f"👤 发送者: {new_message.get('sender', '未知')}")
                    logger.info(f"⏰ 时间戳: {new_message.get('timestamp', '未知')}")

                    # 串行处理这条消息
                    process_start_time = time.time()
                    await self._process_single_message(new_message)
                    process_time = time.time() - process_start_time

                    logger.info(f"✅ [{message_count}] 消息处理完毕 (处理耗时: {process_time:.1f}秒)")
                    logger.info(f"📊 总周期耗时: {time.time() - cycle_start_time:.1f}秒")
                else:
                    # 没有新消息，可能是正常的空闲周期
                    wait_time = time.time() - cycle_start_time
                    if wait_time > 30:  # 如果等待超过30秒，记录一下
                        logger.debug(f"⏳ 本轮未检测到新消息 (等待耗时: {wait_time:.1f}秒)")

            except KeyboardInterrupt:
                logger.info("⛔ 接收到中断信号，停止监控新消息")
                self.is_running = False
                break
            except asyncio.CancelledError:
                logger.info("⛔ 监控任务被取消，停止监控新消息")
                self.is_running = False
                break
            except Exception as e:
                error_count += 1
                logger.error(f"❌ [{error_count}] 监控消息失败: {e}")
                import traceback
                logger.error(f"🔍 详细错误信息: {traceback.format_exc()}")

                # 错误恢复策略
                if error_count % 5 == 0:
                    logger.warning(f"⚠️ 连续错误{error_count}次，尝试重新初始化页面...")
                    try:
                        await self.page_manager.ensure_active_page()
                        logger.info("✅ 页面重新初始化完成")
                    except Exception as recovery_error:
                        logger.error(f"❌ 页面重新初始化失败: {recovery_error}")

                await asyncio.sleep(5)

        # 监控结束统计
        total_time = time.time() - monitor_start_time
        logger.info("📱 ===== 消息监控已停止 =====")
        logger.info(f"📊 最终统计: 运行时间{total_time/60:.1f}分钟, 处理消息{message_count}条, 错误{error_count}次")
        if message_count > 0:
            logger.info(f"📊 平均处理速度: {message_count/(total_time/60):.2f}条/分钟")

    async def _wait_for_next_new_message(self, poll_interval: float = 5.0) -> Optional[Dict]:
        """等待下一条新消息 - 结合新消息标记和持久化存储判断"""
        check_count = 0

        while self.is_running:
            try:
                check_count += 1

                # 每100次检查记录一次状态
                if check_count % 100 == 1:
                    logger.debug(f"🔍 消息检查周期 #{check_count}, 轮询间隔: {poll_interval}秒")

                # 1. 首先确保页面有效并检查有新消息标记的联系人
                try:
                    await self.page_manager.ensure_active_page()
                    logger.debug("🎯 检查有新消息标记的联系人...")
                    contacts_with_indicators = await self.check_for_new_message_indicators()
                except Exception as page_error:
                    logger.error(f"📄 页面操作失败: {page_error}")
                    logger.warning("🔄 尝试重新初始化浏览器组件...")
                    try:
                        # 重新初始化DOM解析器
                        if self.page_manager.page and not self.page_manager.page.is_closed():
                            self.page_manager.dom_parser = GoofishDOMParser(self.page_manager.page)
                        else:
                            logger.error("❌ 页面已关闭，无法重新初始化")
                            await asyncio.sleep(poll_interval * 3)  # 延长等待时间
                            continue
                    except Exception as init_error:
                        logger.error(f"❌ 重新初始化失败: {init_error}")
                        await asyncio.sleep(poll_interval * 3)
                        continue

                    # 重试获取联系人
                    try:
                        contacts_with_indicators = await self.check_for_new_message_indicators()
                    except Exception as retry_error:
                        logger.error(f"❌ 重试获取联系人失败: {retry_error}")
                        await asyncio.sleep(poll_interval * 2)
                        continue

                if not contacts_with_indicators:
                    # 没有新消息标记，等待后继续
                    logger.debug(f"⏳ 未发现新消息标记，等待{poll_interval}秒后继续...")
                    await asyncio.sleep(poll_interval)
                    continue

                logger.info(f"🎉 发现 {len(contacts_with_indicators)} 个有新消息标记的联系人")

                # 2. 遍历有新消息标记的联系人，检查具体的新消息
                for i, contact in enumerate(contacts_with_indicators):
                    contact_name = contact['name']
                    logger.info(f"🔍 [{i+1}/{len(contacts_with_indicators)}] 检查联系人: {contact_name}")

                    # 进入该联系人的聊天
                    select_start_time = time.time()
                    if not await self.select_contact(contact_name):
                        logger.warning(f"❌ 无法进入联系人 {contact_name} 的聊天")
                        continue

                    select_time = time.time() - select_start_time
                    logger.debug(f"✅ 成功进入联系人 {contact_name} 的聊天 (耗时: {select_time:.1f}秒)")

                    # 获取该联系人的最新消息
                    get_messages_start_time = time.time()
                    current_messages = await self.get_chat_messages(contact_name)
                    get_messages_time = time.time() - get_messages_start_time

                    logger.debug(f"📋 获取到 {len(current_messages)} 条聊天消息 (耗时: {get_messages_time:.1f}秒)")

                    # 找到真正的新消息
                    find_start_time = time.time()
                    new_message = self.data_persistence.find_new_message_for_contact(contact_name, current_messages)
                    find_time = time.time() - find_start_time

                    if new_message:
                        logger.info(f"🎉 在联系人 {contact_name} 中找到新消息!")
                        logger.info(f"📝 新消息内容: {new_message.get('text', '')[:50]}...")
                        logger.debug(f"⏱️ 查找耗时: {find_time:.1f}秒")

                        # 更新持久化存储
                        self.data_persistence.update_last_processed_message(contact_name, new_message)
                        logger.debug(f"💾 已更新联系人 {contact_name} 的消息记录")

                        return new_message
                    else:
                        logger.debug(f"⚠️ 联系人 {contact_name} 虽有标记但未找到真正新消息")

                # 所有有标记的联系人都检查完了，但没找到真正的新消息
                logger.debug(f"⚠️ 检查完所有有标记的联系人，但未找到真正新消息，可能是误报")
                logger.debug(f"⏳ 等待{poll_interval}秒后继续...")
                await asyncio.sleep(poll_interval)

            except KeyboardInterrupt:
                logger.info("⛔ 接收到中断信号，停止等待新消息")
                self.is_running = False
                raise
            except asyncio.CancelledError:
                logger.info("⛔ 等待新消息任务被取消")
                self.is_running = False
                raise
            except Exception as e:
                logger.error(f"❌ 等待新消息时出错: {e}")
                import traceback
                logger.error(f"🔍 详细错误信息: {traceback.format_exc()}")

                # 错误后延长等待时间
                error_wait_time = poll_interval * 2
                logger.warning(f"⏳ 出错后等待{error_wait_time}秒后重试...")
                await asyncio.sleep(error_wait_time)

        logger.debug("🔚 等待新消息循环结束")
        return None

    async def _process_single_message(self, message: Dict):
        """处理单条消息 - 确保完全处理完毕再返回"""
        try:
            if not self.message_callback:
                logger.warning("没有设置消息处理回调函数")
                return

            logger.debug(f"开始处理消息: {message}")

            # 调用回调函数处理消息
            if asyncio.iscoroutinefunction(self.message_callback):
                await self.message_callback(message)
            else:
                # 对于同步回调函数，在线程池中执行以避免阻塞
                await asyncio.get_event_loop().run_in_executor(None, self.message_callback, message)

            logger.debug(f"消息处理成功: {message.get('text', '')[:50]}...")

        except Exception as e:
            logger.error(f"处理单条消息失败: {e}")
            logger.error(f"消息内容: {message}")
            # 不重新抛出异常，继续处理下一条消息

    async def check_for_new_message_indicators(self) -> List[Dict]:
        """检查有新消息标记的联系人 - 重用DOM解析器"""
        try:
            if not self.page_manager.dom_parser:
                logger.error("DOM解析器未初始化")
                return []

            # 直接使用DOM解析器的方法
            contacts_with_new_messages = await self.page_manager.dom_parser.get_contacts_with_new_messages()

            # 转换格式以保持兼容性
            formatted_contacts = []
            for contact in contacts_with_new_messages:
                formatted_contacts.append({
                    'name': contact['name'],
                    'avatar': '',  # DOM解析器暂未提供avatar信息
                    'last_message': contact.get('last_message', ''),
                    'has_new_message_indicator': contact.get('has_new_message', False)
                })
                logger.debug(f"联系人 {contact['name']} 有新消息标记")

            return formatted_contacts

        except Exception as e:
            logger.error(f"检查新消息标记失败: {e}")
            return []

    async def select_contact(self, contact_name: str) -> bool:
        """选择联系人进入聊天"""
        try:
            if not self.page_manager.dom_parser:
                logger.error("DOM解析器未初始化")
                return False

            # 使用DOM解析器选择联系人
            success = await self.page_manager.dom_parser.select_contact(contact_name)
            return success

        except Exception as e:
            logger.error(f"选择联系人失败: {e}")
            return False

    async def get_chat_messages(self, contact_name: str = None) -> List[Dict]:
        """获取聊天消息"""
        try:
            # 确保使用活跃页面
            await self.page_manager.ensure_active_page()
            if not self.page_manager.dom_parser:
                logger.error("DOM解析器未初始化")
                return []

            # 使用DOM解析器提取消息，传入联系人名称
            messages = await self.page_manager.dom_parser.get_chat_messages(contact_name=contact_name)

            # 只返回接收到的消息
            received_messages = []
            for message in messages:
                if message.get('is_received', False):
                    received_messages.append({
                        'text': message['text'],
                        'sender': message['sender'],
                        'timestamp': message['timestamp'],
                        'type': 'received'
                    })

            return received_messages

        except Exception as e:
            logger.error(f"获取聊天消息失败: {e}")
            return []

    def stop_monitoring(self):
        """停止监控"""
        self.is_running = False
        logger.info("消息监控已停止")