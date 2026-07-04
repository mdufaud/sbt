"""
Declarative vcpkg port overlays for SBT.

Lets app.py declare `vcpkg_ports = {"<port>": {...}}` to override a stock vcpkg
port without hand-writing a full manual overlay. For each declared port we copy
the stock port into a generated overlay dir and apply the declared edits.

Per-port schema (all keys optional):
    "patches":        [<path>, ...]   patch files (rel to addon/vcpkg/) copied
                                      beside the portfile and merged into the
                                      source-extract call's PATCHES argument.
    "remove_patches": [<name>, ...]   stock patch basenames dropped from PATCHES
                                      (and the .patch file removed).
    "manifest":       {<key>: <val>}  shallow merge into the port's vcpkg.json
                                      (e.g. default-features, port-version,
                                      version-semver).
    "files":          {<src>: <dst>}  files (src rel to addon/vcpkg/) copied into
                                      the generated port at <dst>.
    "recipe_patches": [<path>, ...]   patch files (rel to addon/vcpkg/) applied
                                      with `git apply` to the generated port dir
                                      (portfile.cmake / vcpkg.json edits: SHA pin,
                                      option splice, guard change, block deletion,
                                      file removal). Applied last.

Manual overlays in addon/vcpkg/overlay-ports/ stay valid; a port may be in
vcpkg_ports OR have a manual overlay, not both.
"""

import json
import os
import re
import shutil
import subprocess

from sbt.core import logger

# Source-acquisition functions whose extracted path we can patch.
# Longest names first so the alternation prefers the more specific match.
_EXTRACT_FUNCS = (
    "vcpkg_extract_source_archive_ex",
    "vcpkg_extract_source_archive",
    "vcpkg_from_github",
    "vcpkg_from_gitlab",
    "vcpkg_from_bitbucket",
    "vcpkg_from_sourceforge",
    "vcpkg_from_git",
)

_CALL_RE = re.compile(r"\b(" + "|".join(_EXTRACT_FUNCS) + r")\s*\(")


def _matching_paren(text: str, open_idx: int) -> int:
    """Return index of the ')' matching the '(' at open_idx, or -1."""
    depth = 0
    for i in range(open_idx, len(text)):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _is_commented(text: str, idx: int) -> bool:
    """True if a '#' precedes idx on the same line (cmake comment)."""
    line_start = text.rfind("\n", 0, idx) + 1
    return "#" in text[line_start:idx]


def _find_source_path_call(text: str):
    """
    Locate the extract call producing the variable SOURCE_PATH.
    Returns (open_idx, close_idx) of its argument block, or None.
    """
    for m in _CALL_RE.finditer(text):
        if _is_commented(text, m.start()):
            continue
        func = m.group(1)
        open_idx = m.end() - 1
        close_idx = _matching_paren(text, open_idx)
        if close_idx == -1:
            continue
        block = text[open_idx + 1 : close_idx]
        if func == "vcpkg_extract_source_archive":
            # new signature: first positional token is the out-var
            first = re.match(r"\s*([A-Za-z0-9_]+)", block)
            if first and first.group(1) == "SOURCE_PATH":
                return open_idx, close_idx
        else:
            if re.search(r"\bOUT_SOURCE_PATH\s+SOURCE_PATH\b", block):
                return open_idx, close_idx
    return None


def _inject_patches(text: str, basenames: list[str]) -> str | None:
    """
    Merge basenames into the SOURCE_PATH extract call's PATCHES list.
    Returns the new portfile text, or None if no extract call was found.
    """
    found = _find_source_path_call(text)
    if found is None:
        return None
    open_idx, close_idx = found
    block = text[open_idx + 1 : close_idx]

    pm = re.search(r"\bPATCHES\b", block)
    if pm:
        # Determine indentation from the first existing value, default 4 spaces.
        after = block[pm.end() :]
        vm = re.search(r"\n([ \t]+)\S", after)
        indent = vm.group(1) if vm else "    "
        # PATCHES value list runs until the next ALL-CAPS keyword token or block end.
        boundary = len(block)
        for tok in re.finditer(r"[^\s()]+", after):
            if re.fullmatch(r"[A-Z][A-Z0-9_]*", tok.group(0)):
                boundary = pm.end() + tok.start()
                break
        # Insert complete lines right after the last existing value line.
        abs_boundary = open_idx + 1 + boundary
        insert_at = text.rfind("\n", 0, abs_boundary) + 1
        addition = "".join(f"{indent}{b}\n" for b in basenames)
    else:
        # No PATCHES keyword: add a fresh block before the closing ')'.
        addition = "    PATCHES\n" + "\n".join(f"        {b}" for b in basenames) + "\n"
        addition = "\n" + addition
        insert_at = close_idx

    return text[:insert_at] + addition + text[insert_at:]


def _remove_patch_lines(text: str, port: str, names: list[str]) -> str:
    """Drop each patch basename from its one-per-line PATCHES entry."""
    for name in names:
        pat = re.compile(r"^[ \t]*" + re.escape(name) + r"[ \t]*(?:#[^\n]*)?\n", re.M)
        text, n = pat.subn("", text)
        if n == 0:
            logger.error(f"vcpkg_ports: remove_patches '{name}' not found in {port}/portfile.cmake")
            raise RuntimeError(f"vcpkg_ports: remove_patches '{name}' not found for port '{port}'")
    return text


def _apply_recipe_patches(dst_port: str, port: str, patch_paths, addon_vcpkg_path: str) -> None:
    """Apply recipe patch files to the generated port dir via `git apply`."""
    # The generated port dir lives under build/, inside the project git repo. `git apply`
    # discovers that parent repo and then silently no-ops file *deletions* in the patch
    # (it operates relative to the repo instead of the filesystem). Point GIT_DIR at a
    # nonexistent path so git treats dst_port as standalone and applies deletions on disk.
    env = dict(os.environ)
    env["GIT_DIR"] = os.path.join(dst_port, ".sbt-no-repo")
    for patch_rel in patch_paths:
        patch_abs = os.path.join(addon_vcpkg_path, patch_rel)
        if not os.path.isfile(patch_abs):
            logger.error(f"vcpkg_ports: recipe_patch file not found: {patch_abs}")
            raise RuntimeError(f"vcpkg_ports: missing recipe_patch '{patch_rel}' for port '{port}'")
        proc = subprocess.run(
            # --ignore-whitespace: stock vcpkg ports drift between LF/CRLF across baseline
            # bumps (a single port can even be mixed), so match patch context ignoring EOL.
            ["git", "-c", "core.autocrlf=false", "apply", "--whitespace=nowarn", "--ignore-whitespace", patch_abs],
            cwd=dst_port,
            capture_output=True,
            check=False,
            env=env,
        )
        if proc.returncode != 0:
            logger.error(
                f"vcpkg_ports: recipe_patch '{patch_rel}' failed to apply to port '{port}':\n"
                f"{proc.stderr.decode(errors='replace')}"
            )
            raise RuntimeError(f"vcpkg_ports: recipe_patch '{patch_rel}' failed for port '{port}'")


def _merge_manifest(dst_port: str, port: str, manifest: dict) -> None:
    """Shallow-merge keys into the port's vcpkg.json."""
    path = os.path.join(dst_port, "vcpkg.json")
    if not os.path.isfile(path):
        logger.error(f"vcpkg_ports: vcpkg.json not found for port '{port}': {path}")
        raise RuntimeError(f"vcpkg_ports: missing vcpkg.json for port '{port}'")
    with open(path, "r") as f:
        data = json.load(f)
    data.update(manifest)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _portfile_matches_baseline(vcpkg_root: str, baseline: str, port: str, worktree_portfile: str) -> bool | None:
    """
    Compare the working-tree portfile against the baseline-pinned tree.
    Returns True/False, or None if the git lookup failed (cannot decide).
    """
    proc = subprocess.run(
        ["git", "-C", vcpkg_root, "show", f"{baseline}:ports/{port}/portfile.cmake"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    try:
        with open(worktree_portfile, "rb") as f:
            current = f.read()
    except OSError:
        return None
    return current == proc.stdout


def generate_overlay_ports(
    app,
    vcpkg_ports_path: str,
    gen_dir: str,
    vcpkg_root: str,
    baseline: str,
    addon_vcpkg_path: str,
    addon_overlay_ports_path: str,
) -> str | None:
    """
    Build generated overlay ports from app.vcpkg_ports.

    Returns the gen_dir path to pass as --overlay-ports, or None when no
    ports are declared. Raises RuntimeError on misconfiguration.
    """
    ports = getattr(app, "vcpkg_ports", {})
    if not ports:
        return None

    if os.path.isdir(gen_dir):
        shutil.rmtree(gen_dir)
    os.makedirs(gen_dir)

    for port, spec in ports.items():
        # Cannot have both a manual overlay and a generated overlay for one port.
        if os.path.isdir(os.path.join(addon_overlay_ports_path, port)):
            logger.error(
                f"vcpkg_ports: port '{port}' also has a manual overlay in overlay-ports/; "
                f"remove one. Use vcpkg_ports OR a manual overlay, not both."
            )
            raise RuntimeError(f"vcpkg_ports conflict for port '{port}'")

        src_port = os.path.join(vcpkg_ports_path, port)
        src_portfile = os.path.join(src_port, "portfile.cmake")
        if not os.path.isfile(src_portfile):
            logger.error(f"vcpkg_ports: stock port not found: {src_port}")
            raise RuntimeError(f"vcpkg_ports: unknown port '{port}'")

        matches = _portfile_matches_baseline(vcpkg_root, baseline, port, src_portfile)
        if matches is False:
            logger.warning(
                f"vcpkg_ports: working-tree portfile for '{port}' differs from pinned "
                f"baseline {baseline[:12]}; generated overlay copies the working tree, "
                f"which may not match what manifest mode would otherwise build."
            )

        dst_port = os.path.join(gen_dir, port)
        shutil.copytree(src_port, dst_port)
        dst_portfile = os.path.join(dst_port, "portfile.cmake")

        with open(dst_portfile, "r", newline="") as f:
            text = f.read()

        # 1. remove stock patches (drop from PATCHES + delete the file)
        remove_patches = spec.get("remove_patches", [])
        if remove_patches:
            text = _remove_patch_lines(text, port, remove_patches)
            for name in remove_patches:
                stock = os.path.join(dst_port, name)
                if os.path.isfile(stock):
                    os.remove(stock)

        # 2. add patches (copy + merge into PATCHES)
        basenames = []
        for patch_rel in spec.get("patches", []):
            patch_src = os.path.join(addon_vcpkg_path, patch_rel)
            if not os.path.isfile(patch_src):
                logger.error(f"vcpkg_ports: patch file not found: {patch_src}")
                raise RuntimeError(f"vcpkg_ports: missing patch '{patch_rel}' for port '{port}'")
            basename = os.path.basename(patch_rel)
            shutil.copyfile(patch_src, os.path.join(dst_port, basename))
            basenames.append(basename)
        if basenames:
            injected = _inject_patches(text, basenames)
            if injected is None:
                logger.error(
                    f"vcpkg_ports: no source-extract call producing SOURCE_PATH found in "
                    f"{port}/portfile.cmake; cannot inject patches (use recipe_patches instead)."
                )
                raise RuntimeError(f"vcpkg_ports: cannot inject patches for port '{port}'")
            text = injected

        with open(dst_portfile, "w", newline="") as f:
            f.write(text)

        # 3. vcpkg.json merge
        manifest = spec.get("manifest", {})
        if manifest:
            _merge_manifest(dst_port, port, manifest)

        # 4. inject extra files
        for src_rel, dst_rel in spec.get("files", {}).items():
            file_src = os.path.join(addon_vcpkg_path, src_rel)
            if not os.path.isfile(file_src):
                logger.error(f"vcpkg_ports: file not found: {file_src}")
                raise RuntimeError(f"vcpkg_ports: missing file '{src_rel}' for port '{port}'")
            file_dst = os.path.join(dst_port, dst_rel)
            os.makedirs(os.path.dirname(file_dst), exist_ok=True)
            shutil.copyfile(file_src, file_dst)

        # 5. recipe patches (arbitrary portfile.cmake / vcpkg.json edits) applied last
        recipe_patches = spec.get("recipe_patches", [])
        if recipe_patches:
            _apply_recipe_patches(dst_port, port, recipe_patches, addon_vcpkg_path)

        logger.info(f"vcpkg_ports: generated overlay for '{port}'")

    return gen_dir
