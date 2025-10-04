import client_utils
from android_utils import run_on_ui_thread, log
from client_utils import send_request, get_messages_controller
from java import jint
from ui.settings import Header, Switch, Divider, Input, Text
from java.util import ArrayList
from org.telegram.ui.ActionBar import AlertDialog
from org.telegram.tgnet import TLRPC
from ui.alert import AlertDialogBuilder
from org.telegram.ui.ActionBar import BaseFragment
from org.telegram.messenger import MessageObject, LocaleController, R, ApplicationLoader, UserConfig


__name__ = "Own Messages Deleter"
__description__ = "Удаляет все собственные сообщения в чате/группе.\n\nDeletes all your own message in chat/group."
__icon__ = "Miku_u/11"
__version__ = "1.0.0"
__id__ = "msgsDeleter"
__author__ = "@bleizix"
__min_version__ = "11.12.0"

from ui.bulletin import BulletinHelper
from base_plugin import BasePlugin, MenuItemData, MenuItemType


# thx to NekoGram
class OwnMessagesDeleter(BasePlugin):
    def __init__(self):
        super().__init__()
        self.allCount = 0
    def on_plugin_load(self):
        def show_alert(text):
            try:

                fragment = client_utils.get_last_fragment()
                if fragment is None:
                    return


            except Exception as e:
                log(f"Failed to show alert: {e}")
        def click_wrapper(context: dict):
            try:

                fragment = client_utils.get_last_fragment()
                ctx = fragment.getContext() if fragment else ApplicationLoader.applicationContext
                builder = AlertDialogBuilder(ctx, AlertDialogBuilder.ALERT_TYPE_MESSAGE)
                builder.set_title("Удалить сообщения?")
                builder.set_message("Удалить абсолютно все свои сообщения? Это действие невозможно отменить")
                builder.set_positive_button("Да", lambda dialog, which : self.delete_user_history_with_search(fragment, context.get("dialog_id"), 0, 0, client_utils.get_connections_manager().getCurrentTime(), None))

                ayugram = False
                try:
                    from com.radolyn.ayugram import AyuState
                    ayugram = True
                except Exception as e:
                    ayugram = False

                if (ayugram):
                    builder.set_neutral_button("Да, не сохраняя локально", lambda dialog, which :self.delete_user_history_with_search(fragment, context.get("dialog_id"), 0, 0, client_utils.get_connections_manager().getCurrentTime(), None, True))

                builder.show()




            except Exception as e:
                BulletinHelper.show_error(f"error: {e}")

        lang = LocaleController.getInstance().getCurrentLocale().getLanguage()
        isRussian = True if lang.startswith('ru') else False
        textToShow = "Удал. свои соо." if isRussian else "Delete own msgs"
        self.add_menu_item(
            MenuItemData(
                menu_type=MenuItemType.CHAT_ACTION_MENU,
                text=textToShow,
                on_click=click_wrapper,
                icon="msg_delete_solar"
            )
        )


    def delete_user_history_with_search(self, fragment: BaseFragment, dialog_id: int, reply_message_id: int,
                                        merge_dialog_id: int, before: int, callback: callable = None, fromAyuToo = False):

        def search_and_delete_runnable():
            message_ids = []
            messages_controller = client_utils.get_messages_controller()
            user_config = client_utils.get_user_config()
            peer = messages_controller.getInputPeer(dialog_id)
            from_id = messages_controller.getInputPeer(user_config.getCurrentUser())

            def on_search_complete():
                if message_ids and len(message_ids) > 0:
                    chunked_lists = [message_ids[i:i + 100] for i in range(0, len(message_ids), 100)]

                    def delete_action():
                        ayugram = False
                        try:
                            from com.radolyn.ayugram import AyuState
                            ayugram = True
                        except Exception as e:
                            ayugram = False

                        for id_chunk in chunked_lists:
                            java_list = ArrayList()
                            for msg_id in id_chunk:
                                java_list.add(jint(msg_id))
                                if (ayugram and fromAyuToo):
                                    AyuState.permitDeleteMessage(dialog_id, jint(msg_id))


                            messages_controller.deleteMessages(java_list, None, None, dialog_id, reply_message_id, True,
                                                               0)
                        BulletinHelper.show_info(f"Successfully deleted {len(message_ids)} messages.")

                    if callback:
                        run_on_ui_thread(lambda: callback(len(message_ids), delete_action))
                    else:
                        run_on_ui_thread(delete_action)
                else:
                    BulletinHelper.show_info("No messages from you.")

                if merge_dialog_id != 0:
                    self.delete_user_history_with_search(fragment, merge_dialog_id, 0, 0, before, None, fromAyuToo)

            self._do_search_messages(fragment, on_search_complete, message_ids, peer, reply_message_id, from_id, before,
                                     0, 0)

        client_utils.run_on_queue(search_and_delete_runnable)

    def _do_search_messages(self, fragment: BaseFragment, on_complete: callable, message_ids: list,
                            peer: TLRPC.InputPeer, reply_message_id: int, from_id: TLRPC.InputPeer, before: int,
                            offset_id: int, hash_val: int):

        req = TLRPC.TL_messages_search()
        req.peer = peer
        req.limit = 100
        req.q = ""
        req.offset_id = offset_id
        req.from_id = from_id
        req.flags |= 1
        req.filter = TLRPC.TL_inputMessagesFilterEmpty()
        if reply_message_id != 0:
            req.top_msg_id = reply_message_id
            req.flags |= 2
        req.hash = hash_val

        def on_response(response, error):
            if error:
                run_on_ui_thread(lambda: BulletinHelper.show_error(f"Error\n{error.text}"))
                on_complete()
                return

            if not hasattr(response, 'messages') or not response.messages or response.messages.isEmpty():
                on_complete()
                return

            minId = min(m.id for m in response.messages.toArray())
            for message in response.messages.toArray():

                if not message.out or message.post or message.date >= before:
                    continue
                message_ids.append(message.id)

            self._do_search_messages(fragment, on_complete, message_ids, peer, reply_message_id, from_id, before,
                                     minId, 0)

        connections_manager = client_utils.get_connections_manager()
        connections_manager.sendRequest(req, client_utils.RequestCallback(on_response), 2)
          
