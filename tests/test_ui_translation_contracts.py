"""UI data contracts that must remain aligned after English/Linux adaptation."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.core.remote_file_browser import RemoteFileItem
from app.core.task_database import TaskState
from app.ui.post_processing_window import PostProcessingWindow
from app.ui.ssh_file_transfer_dialog import SSHFileTransferDialog
from app.ui.task_center_window import TaskCenterWindow


class UITranslationContracts(unittest.TestCase):
    def remote_dialog(self):
        kind = RemoteFileItem("results", "/work/results", True, 0, "", "drwx------").type_name
        table = Mock()
        table.selection.return_value = ("row",)
        table.item.side_effect = lambda row, field: "results" if field == "text" else (0, "", "", kind)
        remote = Mock()
        remote.get.return_value = "/work"
        return SimpleNamespace(remote_table=table, remote_dir=remote, refresh_remote=Mock(),
                               client=SimpleNamespace(sftp=Mock()), t=lambda key: key)

    def test_remote_folder_navigation_uses_the_core_type_label(self):
        dialog = self.remote_dialog()
        SSHFileTransferDialog.remote_double_click(dialog)
        dialog.remote_dir.set.assert_called_once_with("/work/results")
        dialog.refresh_remote.assert_called_once()

    def test_remote_folder_delete_uses_rmdir_and_never_file_remove(self):
        dialog = self.remote_dialog()
        with patch("app.ui.ssh_file_transfer_dialog.messagebox.askyesno", return_value=True):
            SSHFileTransferDialog.delete_remote(dialog)
        dialog.client.sftp.rmdir.assert_called_once_with("/work/results")
        dialog.client.sftp.remove.assert_not_called()

    def test_translated_connection_errors_wait_without_consuming_retries(self):
        for message in ("SFTP is not connected", "SSH is disconnected",
                        "Cannot download CONTCAR from the current server directory"):
            with self.subTest(message=message):
                database = Mock()
                database.claim_ready_local_tasks.return_value = [SimpleNamespace(id=1, attempts=3, max_retries=3)]
                window = SimpleNamespace(database=database,
                                         callbacks={"execute_local_task": Mock(side_effect=RuntimeError(message))})
                self.assertEqual(TaskCenterWindow._execute_ready_local_steps(window), (0, 1))
                self.assertEqual(database.set_state.call_args.args[1], TaskState.RETRY_WAIT)
                database.update_task.assert_not_called()

    def test_linux_postprocessing_wheel_moves_both_directions(self):
        canvas = Mock()
        window = SimpleNamespace(_scrollable_canvases=[canvas], winfo_containing=lambda *_: canvas)
        for number, units in ((4, -3), (5, 3)):
            event = SimpleNamespace(num=number, delta=0, x_root=10, y_root=10)
            self.assertEqual(PostProcessingWindow._scroll_content(window, event), "break")
            canvas.yview_scroll.assert_called_with(units, "units")


if __name__ == "__main__":
    unittest.main()
