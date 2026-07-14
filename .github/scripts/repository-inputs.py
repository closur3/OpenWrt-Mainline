#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

from ruamel.yaml import YAML


MANIFEST_PATH = Path(__file__).resolve().parents[2] / ".repo"
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
PRERELEASE_PATTERN = re.compile(r"-(rc|alpha|beta|preview)", re.IGNORECASE)


def fail(message):
    raise SystemExit(message)


def command_lines(*args):
    result = subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        fail(f"{' '.join(args)} failed")
    return result.stdout.splitlines()


def git_lines(*args):
    return command_lines("git", *args)


def run_checked(*args):
    print("+", " ".join(str(arg) for arg in args))
    result = subprocess.run(args, check=False)
    if result.returncode != 0:
        fail(f"{' '.join(str(arg) for arg in args)} failed")


def natural_key(value):
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part.lower())
        for part in re.split(r"(\d+)", value)
        if part
    )


def version_key(tag):
    prerelease = PRERELEASE_PATTERN.search(tag)
    if prerelease:
        return (
            natural_key(tag[: prerelease.start()]),
            0,
            natural_key(tag[prerelease.start() + 1 :]),
        )
    return natural_key(tag), 1, ()


def sort_versions(tags):
    return sorted(tags, key=version_key)


def latest_stable_tag(url):
    tags = [
        match.group(1)
        for line in git_lines("ls-remote", "--tags", "--refs", url)
        if (match := re.search(r"refs/tags/(.+)$", line))
    ]
    tags = [tag for tag in tags if not PRERELEASE_PATTERN.search(tag)]
    ordered = sort_versions(tags)
    return ordered[-1] if ordered else None


def resolve_remote_reference(url, pattern):
    lines = git_lines("ls-remote", url, pattern)
    if not lines:
        return None
    commit = lines[0].split()[0]
    return commit if COMMIT_PATTERN.fullmatch(commit) else None


def resolve_tag(url, tag):
    return (
        resolve_remote_reference(url, f"refs/tags/{tag}^{{}}")
        or resolve_remote_reference(url, f"refs/tags/{tag}")
    )


def resolve_branch(url, branch):
    return resolve_remote_reference(url, f"refs/heads/{branch}")


def load_manifest():
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    manifest = yaml.load(MANIFEST_PATH)
    validate_manifest(manifest)
    return yaml, manifest


def require_mapping(value, label):
    if not isinstance(value, dict):
        fail(f"{label} must be a mapping")


def require_text(item, field, label):
    value = item.get(field)
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        fail(f"{label}.{field} must be a non-empty single-line string")
    return value


def tracking_field(item, label):
    fields = [field for field in ("tag", "branch") if field in item]
    if len(fields) != 1:
        fail(f"{label} must contain exactly one of tag or branch")
    return fields[0], require_text(item, fields[0], label)


def relative_path(value, label, prefixes):
    value = require_text(value, label[1], label[0])
    if "\\" in value:
        fail(f"{label[0]}.{label[1]} must use forward slashes")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        fail(f"{label[0]}.{label[1]} must be a safe relative path")
    if prefixes and path.parts[0] not in prefixes:
        allowed = ", ".join(prefixes)
        fail(f"{label[0]}.{label[1]} must start with one of: {allowed}")
    return path


def validate_entry(name, item, group):
    label = f"{group}.{name}"
    if not isinstance(name, str) or not name:
        fail(f"{group} names must be non-empty strings")
    require_mapping(item, label)

    allowed = {"url", "tag", "branch", "commit"}
    if group == "packages":
        allowed.add("destination")
    elif group == "files":
        allowed.update({"path", "archive_member", "destination"})

    unknown = set(item) - allowed
    if unknown:
        fail(f"{label} has unsupported fields: {', '.join(sorted(unknown))}")

    require_text(item, "url", label)
    tracking_field(item, label)
    commit = require_text(item, "commit", label)
    if not COMMIT_PATTERN.fullmatch(commit):
        fail(f"{label}.commit must be a 40-character lowercase commit")

    if group == "packages":
        relative_path(item, (label, "destination"), ("package", "feeds"))
    elif group == "files":
        relative_path(item, (label, "path"), ())
        relative_path(item, (label, "destination"), ("package", "feeds", "files"))
        if "archive_member" in item:
            require_text(item, "archive_member", label)


def validate_manifest(manifest):
    require_mapping(manifest, ".repo")
    unknown = set(manifest) - {"source", "packages", "files"}
    if unknown:
        fail(f".repo has unsupported sections: {', '.join(sorted(unknown))}")

    source = manifest.get("source")
    require_mapping(source, "source")
    if len(source) != 1:
        fail("source must contain exactly one repository")

    for group in ("source", "packages", "files"):
        entries = manifest.get(group, {})
        require_mapping(entries, group)
        for name, item in entries.items():
            validate_entry(name, item, group)


def update_tracking(name, item):
    url = item["url"]
    tracking_type, current = tracking_field(item, name)

    if tracking_type == "branch":
        commit = resolve_branch(url, current)
        if not commit:
            fail(f"{name}: branch not found: {current}")
        print(f"::notice::⏩ {name}: tracking branch -> {current}")
        return commit

    latest = latest_stable_tag(url)
    if latest is None:
        fail(f"{name}: no stable tags found at {url}")

    if version_key(latest) > version_key(current):
        item["tag"] = latest
        current = latest
        print(f"::notice::⬆️ {name}: updated -> {latest}")
    else:
        print(f"::notice::✅ {name}: up-to-date -> {current}")

    commit = resolve_tag(url, current)
    if not commit:
        fail(f"{name}: tag not found: {current}")
    return commit


def github_repository(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        fail(f"file URL must use https://github.com: {url}")
    repository = parsed.path.strip("/")
    if repository.endswith(".git"):
        repository = repository[:-4]
    if len(repository.split("/")) != 2:
        fail(f"invalid GitHub repository URL: {url}")
    return repository


def github_json(url):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "OpenWrt-Mainline",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token := os.environ.get("GH_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def latest_path_commit(name, item):
    _, tracking_value = tracking_field(item, name)
    query = urllib.parse.urlencode(
        {"sha": tracking_value, "path": item["path"], "per_page": 1}
    )
    repository = github_repository(item["url"])
    commits = github_json(
        f"https://api.github.com/repos/{repository}/commits?{query}"
    )
    if not commits:
        fail(f"{name}: no commit found for {tracking_value}:{item['path']}")
    commit = commits[0].get("sha")
    if not COMMIT_PATTERN.fullmatch(commit or ""):
        fail(f"{name}: invalid path commit: {commit}")
    return commit


def report_commit(name, old_commit, commit, selected_file=False):
    subject = "selected file " if selected_file else ""
    if old_commit == commit:
        print(f"::notice::✅ {name}: {subject}identical -> {commit}")
    elif old_commit:
        print(f"::notice::🔄 {name}: {subject}changed -> {commit}")
    else:
        print(f"::notice::✨ {name}: {subject}added -> {commit}")


def update_manifest(yaml, manifest):
    for group in ("source", "packages"):
        for name, item in manifest.get(group, {}).items():
            old_commit = item["commit"]
            commit = update_tracking(name, item)
            item["commit"] = commit
            report_commit(name, old_commit, commit)

    for name, item in manifest.get("files", {}).items():
        old_commit = item["commit"]
        if "tag" in item:
            update_tracking(name, item)
        else:
            print(f"::notice::⏩ {name}: tracking branch path -> {item['branch']}:{item['path']}")
        commit = latest_path_commit(name, item)
        item["commit"] = commit
        report_commit(name, old_commit, commit, selected_file=True)

    with MANIFEST_PATH.open("w", encoding="utf-8", newline="\n") as stream:
        yaml.dump(manifest, stream)


def source_environment(manifest):
    name, item = next(iter(manifest["source"].items()))
    values = {
        "SOURCE_NAME": name,
        "SOURCE_URL": item["url"],
        "SOURCE_COMMIT": item["commit"],
    }
    if "tag" in item:
        values["SOURCE_TAG"] = item["tag"]
    else:
        values["SOURCE_BRANCH"] = item["branch"]
    for key, value in values.items():
        print(f"{key}={value}")


def target_path(root, value, prefixes):
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.parts[0] not in prefixes:
        fail(f"unsafe destination: {value}")
    return root.joinpath(*path.parts)


def remove_target(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def checkout_package(name, item, root):
    destination = target_path(root, item["destination"], ("package", "feeds"))
    print(f"Checking out {name} at {item['commit']} -> {item['destination']}")
    remove_target(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    run_checked("git", "init", "-q", str(destination))
    run_checked("git", "-C", str(destination), "remote", "add", "origin", item["url"])
    run_checked(
        "git",
        "-C",
        str(destination),
        "fetch",
        "--depth=1",
        "origin",
        item["commit"],
    )
    run_checked(
        "git",
        "-C",
        str(destination),
        "-c",
        "advice.detachedHead=false",
        "checkout",
        "--detach",
        "FETCH_HEAD",
    )
    run_checked(
        "git",
        "-C",
        str(destination),
        "submodule",
        "update",
        "--init",
        "--recursive",
        "--depth",
        "1",
    )
    head = command_lines("git", "-C", str(destination), "rev-parse", "HEAD")
    if head != [item["commit"]]:
        fail(f"{name}: checked out {head[0] if head else 'nothing'}, expected {item['commit']}")


def raw_file_url(item):
    repository = github_repository(item["url"])
    path = urllib.parse.quote(item["path"], safe="/")
    return f"https://raw.githubusercontent.com/{repository}/{item['commit']}/{path}"


def download_file(item):
    headers = {"User-Agent": "OpenWrt-Mainline"}
    if token := os.environ.get("GH_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(raw_file_url(item), headers=headers)

    with urllib.request.urlopen(request, timeout=120) as response:
        with tempfile.NamedTemporaryFile(delete=False) as stream:
            shutil.copyfileobj(response, stream)
            return Path(stream.name)


def install_file(name, item, root):
    destination = target_path(
        root, item["destination"], ("package", "feeds", "files")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    download = download_file(item)
    temporary_output = None

    print(f"Installing {name} -> {item['destination']}")
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, delete=False
        ) as output:
            temporary_output = Path(output.name)
            if member_name := item.get("archive_member"):
                with tarfile.open(download, mode="r:*") as archive:
                    try:
                        member = archive.getmember(member_name)
                    except KeyError:
                        fail(f"{name}: archive member not found: {member_name}")
                    if not member.isfile():
                        fail(f"{name}: archive member is not a regular file: {member_name}")
                    source = archive.extractfile(member)
                    if source is None:
                        fail(f"{name}: cannot extract archive member: {member_name}")
                    with source:
                        shutil.copyfileobj(source, output)
                    output.flush()
                    os.chmod(temporary_output, member.mode & 0o777)
            else:
                with download.open("rb") as source:
                    shutil.copyfileobj(source, output)
                output.flush()
                os.chmod(temporary_output, 0o644)

        os.replace(temporary_output, destination)
        temporary_output = None
    finally:
        download.unlink(missing_ok=True)
        if temporary_output is not None:
            temporary_output.unlink(missing_ok=True)


def materialize(manifest, root_value):
    root = Path(root_value).resolve()
    if not root.is_dir():
        fail(f"materialization root does not exist: {root}")

    for name, item in manifest.get("packages", {}).items():
        checkout_package(name, item, root)

    for name, item in manifest.get("files", {}).items():
        install_file(name, item, root)


def parse_args():
    parser = argparse.ArgumentParser(description="Manage build inputs declared in .repo")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("update")

    environment = commands.add_parser("github-env")
    environment.add_argument("section", choices=("source",))

    materializer = commands.add_parser("materialize")
    materializer.add_argument("--root", default=".")

    return parser.parse_args()


def main():
    args = parse_args()
    yaml, manifest = load_manifest()

    if args.command == "update":
        update_manifest(yaml, manifest)
    elif args.command == "github-env":
        source_environment(manifest)
    elif args.command == "materialize":
        materialize(manifest, args.root)


if __name__ == "__main__":
    main()
