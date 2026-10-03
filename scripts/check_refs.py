#!/usr/bin/env python3
"""Checks the team deployment model: references resolve and releases are pinned.

Needs PyYAML. Renders the chart with helm when helm is on PATH.
"""
import pathlib
import re
import shutil
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENVS = ("dev", "stage", "prod")
GROUPS = ("platform", "backend", "frontend")
TAG = re.compile(r"^(sha-[0-9a-f]{40}|v\d+\.\d+\.\d+)$")
ENV_KEYS = {"env", "cluster", "release", "replicas"}
SERVICE_KEYS = {"name", "group", "image", "tag", "port"}

errors = []


def fail(msg):
    errors.append(msg)


def load(path):
    with open(path) as f:
        return yaml.safe_load(f)


def check_projects():
    for group in GROUPS:
        path = ROOT / "argocd" / "projects" / f"{group}.yaml"
        if not path.exists():
            fail(f"missing project file {path.relative_to(ROOT)}")
            continue
        spec = load(path)["spec"]
        want = {(env, f"{group}-{env}") for env in ENVS}
        got = {(d.get("name"), d.get("namespace")) for d in spec["destinations"]}
        if got != want:
            fail(f"{group}: destinations {sorted(got)} != {sorted(want)}")
        if spec.get("clusterResourceWhitelist") != []:
            fail(f"{group}: clusterResourceWhitelist must be empty")


def check_appsets():
    for env in ENVS:
        path = ROOT / "argocd" / "applicationsets" / f"{env}.yaml"
        if not path.exists():
            fail(f"missing applicationset {path.relative_to(ROOT)}")
            continue
        doc = load(path)
        files = doc["spec"]["generators"][0]["matrix"]["generators"][0]["git"]["files"]
        if files != [{"path": f"envs/{env}.yaml"}]:
            fail(f"{env}: applicationset must read envs/{env}.yaml, got {files}")
        policy = doc["spec"]["template"]["spec"]["syncPolicy"]
        if env == "prod" and "automated" in policy:
            fail("prod must not have automated sync")
        if env != "prod" and not policy.get("automated"):
            fail(f"{env} must have automated sync")


def check_envs_and_releases():
    seen_services = {}
    for env in ENVS:
        path = ROOT / "envs" / f"{env}.yaml"
        if not path.exists():
            fail(f"missing {path.relative_to(ROOT)}")
            continue
        doc = load(path)
        if set(doc) != ENV_KEYS:
            fail(f"{path.name}: keys {sorted(doc)} != {sorted(ENV_KEYS)}")
            continue
        if doc["env"] != env or doc["cluster"] != env:
            fail(f"{path.name}: env and cluster must both be {env}")
        release = ROOT / "releases" / f"{doc['release']}.yaml"
        if not release.exists():
            fail(f"{path.name}: release {doc['release']} has no file")
            continue
        seen_services[env] = release

    for release in sorted((ROOT / "releases").glob("*.yaml")):
        services = load(release)
        if not isinstance(services, list) or not services:
            fail(f"{release.name}: must be a non-empty list")
            continue
        names = set()
        for svc in services:
            if set(svc) != SERVICE_KEYS:
                fail(f"{release.name}: {svc.get('name')} keys {sorted(svc)} != {sorted(SERVICE_KEYS)}")
                continue
            if svc["name"] in names:
                fail(f"{release.name}: duplicate service {svc['name']}")
            names.add(svc["name"])
            if svc["group"] not in GROUPS:
                fail(f"{release.name}: {svc['name']} has unknown group {svc['group']}")
            if not TAG.match(str(svc["tag"])):
                fail(f"{release.name}: {svc['name']} tag {svc['tag']!r} is not an immutable tag")
            if ":" in svc["image"].rsplit("/", 1)[-1] or "@" in svc["image"]:
                fail(f"{release.name}: {svc['name']} image must not carry a tag or digest")
    return seen_services


def render(seen):
    if not shutil.which("helm"):
        print("helm not found, skipping chart render")
        return
    for env, release in seen.items():
        replicas = load(ROOT / "envs" / f"{env}.yaml")["replicas"]
        for svc in load(release):
            cmd = [
                "helm", "template", svc["name"], str(ROOT / "charts" / "service"),
                "--set", f"name={svc['name']}", "--set", f"env={env}",
                "--set", f"image.repository={svc['image']}",
                "--set-string", f"image.tag={svc['tag']}",
                "--set", f"port={svc['port']}", "--set", f"replicas={replicas}",
            ]
            out = subprocess.run(cmd, capture_output=True, text=True)
            if out.returncode != 0:
                fail(f"helm template {svc['name']}/{env}: {out.stderr.strip()}")
            elif f"{svc['image']}:{svc['tag']}" not in out.stdout:
                fail(f"{svc['name']}/{env}: rendered image does not match the release pin")


check_projects()
check_appsets()
render(check_envs_and_releases())

if errors:
    print("\n".join(f"FAIL {e}" for e in errors), file=sys.stderr)
    sys.exit(1)
print("team model references and pins ok")
