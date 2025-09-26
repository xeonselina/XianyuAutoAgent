import json
import hashlib
from typing import Dict
from pathlib import Path
from loguru import logger


class DataPersistence:
    """数据持久化管理器 - 负责消息历史和联系人状态的存储"""

    def __init__(self, data_dir: str = "./goofish_data"):
        # 数据存储配置
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.last_messages_file = self.data_dir / "last_messages.json"
        self.contact_states_file = self.data_dir / "contact_states.json"

        # 加载持久化数据
        self.last_processed_messages = self._load_last_messages()
        self.contact_states = self._load_contact_states()

    def _load_last_messages(self) -> Dict[str, str]:
        """加载最后处理的消息记录"""
        try:
            if self.last_messages_file.exists():
                with open(self.last_messages_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"已加载最后处理的消息记录: {len(data)} 个联系人")
                return data
        except Exception as e:
            logger.error(f"加载消息记录失败: {e}")
        return {}

    def _save_last_messages(self):
        """保存最后处理的消息记录"""
        try:
            with open(self.last_messages_file, 'w', encoding='utf-8') as f:
                json.dump(self.last_processed_messages, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存消息记录失败: {e}")

    def _load_contact_states(self) -> Dict[str, Dict]:
        """加载联系人状态记录"""
        try:
            if self.contact_states_file.exists():
                with open(self.contact_states_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"已加载联系人状态记录: {len(data)} 个联系人")
                return data
        except Exception as e:
            logger.error(f"加载联系人状态失败: {e}")
        return {}

    def _save_contact_states(self):
        """保存联系人状态记录"""
        try:
            with open(self.contact_states_file, 'w', encoding='utf-8') as f:
                json.dump(self.contact_states, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存联系人状态失败: {e}")

    def generate_message_hash(self, message: Dict) -> str:
        """生成消息的唯一哈希标识"""
        # 使用消息内容、时间戳、发送者生成唯一标识
        content = f"{message.get('text', '')}{message.get('timestamp', '')}{message.get('sender', '')}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()

    def find_new_message_for_contact(self, contact_name: str, messages: list) -> Dict:
        """为特定联系人找到新消息"""
        try:
            if not messages:
                return None

            # 获取该联系人最后处理的消息哈希
            last_message_hash = self.last_processed_messages.get(contact_name, "")

            # 从最新消息开始检查
            for message in reversed(messages):
                message_hash = self.generate_message_hash(message)

                # 如果找到了之前处理过的消息，说明后面的都是新消息
                if message_hash == last_message_hash:
                    break

                # 这是一条新消息
                if message.get('type') == 'received':  # 只处理收到的消息
                    logger.debug(f"找到联系人 {contact_name} 的新消息: {message.get('text', '')[:30]}")
                    return message

            # 如果没有找到之前的消息标记，可能是首次处理该联系人
            # 只处理最新的一条收到的消息
            for message in reversed(messages):
                if message.get('type') == 'received':
                    if not last_message_hash:  # 首次处理
                        logger.debug(f"首次处理联系人 {contact_name}，获取最新消息: {message.get('text', '')[:30]}")
                        return message
                    break

            return None

        except Exception as e:
            logger.error(f"查找联系人 {contact_name} 新消息时出错: {e}")
            return None

    def update_last_processed_message(self, contact_name: str, message: Dict):
        """更新联系人最后处理的消息"""
        try:
            message_hash = self.generate_message_hash(message)
            self.last_processed_messages[contact_name] = message_hash

            # 立即保存到磁盘
            self._save_last_messages()

            logger.debug(f"更新联系人 {contact_name} 最后处理的消息: {message_hash[:8]}...")

        except Exception as e:
            logger.error(f"更新最后处理消息时出错: {e}")

    def reset_message_history(self, contact_name: str = None):
        """重置消息历史记录（用于测试或重新开始）"""
        if contact_name:
            # 重置特定联系人的消息历史
            if contact_name in self.last_processed_messages:
                del self.last_processed_messages[contact_name]
                self._save_last_messages()
                logger.info(f"已重置联系人 {contact_name} 的消息历史")
        else:
            # 重置所有消息历史
            self.last_processed_messages.clear()
            self._save_last_messages()
            logger.info("已重置所有消息历史")

    def get_message_stats(self) -> Dict:
        """获取消息处理统计信息"""
        return {
            'total_contacts': len(self.last_processed_messages),
            'contacts_with_history': list(self.last_processed_messages.keys()),
            'data_dir': str(self.data_dir),
            'last_messages_file': str(self.last_messages_file),
            'contact_states_file': str(self.contact_states_file)
        }

    def save_all(self):
        """保存所有持久化数据"""
        self._save_last_messages()
        self._save_contact_states()
        logger.info("已保存持久化数据")