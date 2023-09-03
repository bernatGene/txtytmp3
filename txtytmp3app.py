from functools import partial
import yaml
from typing import Iterable
from pathlib import Path
from pytube import YouTube
from pytube.streams import Stream
from pytube.exceptions import RegexMatchError

from textual import work, on
from textual.worker import Worker
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll, Horizontal, Vertical
from textual.message import Message
from textual.widgets import (
    Input,
    Markdown,
    DirectoryTree,
    Button,
    Select,
    ProgressBar,
    Static,
    Switch,
)
from textual.widget import Widget


class Donwload(Button):
    stream: Stream = None
    location: Path | None = None

    class DownloadProgress(Message):
        def __init__(self, remaining) -> None:
            self.remaining = remaining
            super().__init__()

    async def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        self.log("Capture change", event)

    def logged_on_progress(self, default_on_progress, chunk, handler, remaining):
        self.log("On Progress", remaining)
        self.post_message(self.DownloadProgress(remaining))
        default_on_progress(chunk, handler, remaining)

    @work(exclusive=True, thread=True)
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Event handler called when a button is pressed."""
        if self.stream is not None:
            default_on_progress = self.stream.on_progress
            self.stream.on_progress = partial(
                self.logged_on_progress, default_on_progress
            )
            self.label = "Downloading..."
            self.stream.download(output_path=self.location, skip_existing=False)
            self.label = "Done"
        else:
            self.label = "Error. Click to retry"


class StreamSelect(Select):
    class Selected(Message):
        def __init__(self, stream) -> None:
            self.stream = stream
            super().__init__()

    @on(Select.Changed)
    def select_changed(self, event: Select.Changed) -> None:
        self.title = str(event.value)
        self.post_message(self.Selected(event.value))


class FilteredDirectoryTree(DirectoryTree):
    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [
            path for path in paths if (not path.name.startswith(".") and path.is_dir())
        ]


class DonwloadLocation(Widget):
    def __init__(
        self,
        *children: Widget,
        default_loc=None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        if default_loc is not None:
            self.default_loc = default_loc
        else:
            self.default_loc = Path.home().as_posix()
        self.selected_path = self.default_loc
        super().__init__(
            *children, name=name, id=id, classes=classes, disabled=disabled
        )

    class SelectedPath(Message):
        def __init__(self, selected_path) -> None:
            self.selected_path = selected_path
            super().__init__()

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="scrollable"):
            yield Markdown("## Download location")
            yield Static(f"Current Location: {self.default_loc}", id="locationbanner")
            yield Horizontal(
                Static("on:      ", classes="label", id="s_exp_hide"),
                Switch(value=True),
                Button(label="Set as default", id="defaultloc"),
                classes="container",
            )
            yield FilteredDirectoryTree(Path.home(), id="dirtree")

    @work(exclusive=True, thread=True)
    def write_default_loc(self, new_path: Path):
        cfg_path = Path(".cfg.yaml")
        cfgs = {}
        if cfg_path.is_file():
            cfgs = yaml.safe_load(cfg_path.read_text())
        cfgs["download_loc"] = new_path.as_posix()
        cfg_path.write_text(yaml.safe_dump(cfgs))

    @on(Button.Pressed)
    def set_default_loc(self, event: Button.Pressed):
        self.write_default_loc(self.selected_path)

    @on(Switch.Changed)
    def toggle_exp_hide(self, event: Switch.Changed):
        show = event.value
        if show:
            self.query_one("#s_exp_hide", Static).update("Hide: ")
            self.query_one("#dirtree", FilteredDirectoryTree).visible = True
        else:
            self.query_one("#s_exp_hide", Static).update("Explore: ")
            self.query_one("#dirtree", FilteredDirectoryTree).visible = False

    @on(SelectedPath)
    def change_download_location(self, event: SelectedPath):
        self.selected_path = event.selected_path
        self.query_one("#locationbanner", Static).update(
            f"Current Location: {event.selected_path}"
        )

    @on(DirectoryTree.NodeHighlighted)
    def changed_root(self, event: DirectoryTree.NodeHighlighted):
        self.post_message(self.SelectedPath(event.node.data.path))


class YT2MP3(App):
    """Download youtube audio"""

    CSS_PATH = "style.tcss"
    video = None
    path = "./"
    cfgs = None

    def parse_config(self):
        cfg_path = Path(".cfg.yaml")
        cfgs = {"download_loc": Path.home().as_posix()}
        if cfg_path.is_file():
            with open(cfg_path, "r") as read:
                cfgs.update(yaml.safe_load(read) or {})
        self.cfgs = cfgs

    def compose(self) -> ComposeResult:
        self.parse_config()
        yield Input(id="url", placeholder="youtube URL")
        with Horizontal():
            with Vertical(id="results-container"):
                yield Markdown(id="results")
                yield StreamSelect(id="tracks", options=[])
                yield Donwload(id="download", label="Download")
                yield ProgressBar(id="dprog", show_eta=False)
            yield DonwloadLocation(id="path", default_loc=self.cfgs["download_loc"])

    def on_mount(self) -> None:
        """Called when app starts."""
        # Give the input focus, so we can start typing straight away
        self.query_one("#tracks", StreamSelect).display = False
        self.query_one("#dprog", ProgressBar).display = False
        # self.query_one("#dirtree", DirectoryTree).display = False
        self.query_one("#url", Input).focus()

    async def on_input_changed(self, message: Input.Changed) -> None:
        """A coroutine to handle a text changed message."""
        self.query_one("#results", Markdown).update("Searching...")
        if message.value:
            self.find_video(message.value)
        else:
            # Clear the results
            self.query_one("#results", Markdown).update("")

    @on(Switch.Changed)
    def focus_url(self, event: Switch.Changed):
        if not event.value:
            self.query_one("#results", Markdown).focus()

    @on(DonwloadLocation.SelectedPath)
    def change_download_location(self, event: DonwloadLocation.SelectedPath):
        self.query_one("#download", Donwload).location = event.selected_path

    @on(StreamSelect.Selected)
    def selected_stream(self, event: StreamSelect.Selected) -> None:
        self.log("select changed", str(event.stream))
        self.query_one("#download").stream = event.stream
        self.query_one("#download").label = "Download"
        self.log("Filesize", event.stream.filesize)
        self.query_one("#dprog", ProgressBar).total = event.stream.filesize
        self.query_one("#dprog", ProgressBar).progress = 0

    @on(Donwload.DownloadProgress)
    def download_progress(self, event: Donwload.DownloadProgress) -> None:
        dprog = self.query_one("#dprog", ProgressBar)
        # dprog.update(dprog.total,  dprog.total - event.remaining)
        advance = (dprog.total - event.remaining) - dprog.progress
        dprog.advance(advance)
        self.log(
            "advance progress bar",
            dprog.total,
            event.remaining,
            dprog.total - event.remaining,
            dprog.percentage,
            advance,
        )
        # self.query_one("#results", Markdown).update(str(event.remaining))

    @work(exclusive=True, thread=True)
    async def find_video(self, url: str) -> None:
        try:
            self.video = YouTube(url)
        except RegexMatchError:
            self.video = None
        if self.video is not None:
            self.fill_audio_tracks()
            markdown = self.make_word_markdown()
            self.query_one("#download", Button).display = True
            self.query_one("#tracks", StreamSelect).display = True
            self.query_one("#dprog", ProgressBar).display = True
        else:
            markdown = ""
            self.query_one("#download", Button).display = False
            self.query_one("#tracks", StreamSelect).display = False
        self.query_one("#results", Markdown).update(markdown)

    def fill_audio_tracks(self):
        tracks = self.video.streams.filter(only_audio=True)
        self.log(tracks)
        tracks_w = self.query_one("#tracks", Select)
        tracks_w.set_options((str(t), t) for t in tracks)
        tracks_w.value = tracks[0]
        self.post_message(StreamSelect.Selected(tracks[0]))

    def make_word_markdown(self) -> str:
        """Convert the results in to markdown."""
        mkdown = f"""
- **Title**: {self.video.title}
- **Channel**: {self.video.author}
- **Length**: {self.video.length}
        """
        return mkdown


if __name__ == "__main__":
    app = YT2MP3()
    app.run()
