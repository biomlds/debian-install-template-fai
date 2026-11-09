# Portable Sway desktop

The installer ships a minimal Sway fallback. The published
[biomlds/sway-chezmoi-portable](https://github.com/biomlds/sway-chezmoi-portable)
project is the intended optional, user-managed desktop layer: use its complete
repository and [workstation workflow](https://github.com/biomlds/sway-chezmoi-portable/blob/main/docs/workstation.md) rather than copying its generated
files into the FAI config space.

The SWAY package class includes the portable required/recommended Debian desktop
dependencies. FAI still owns LightDM and the session-scoped OpenSSH agent.
`workstation-sway-session` delegates to `~/.local/bin/desktop-sway-session` if the
user has explicitly applied it; otherwise it starts the fallback desktop.
The portable Sway config must retain the system config.d include so KeePassXC and
distribution portal/environment hooks run.

Apply chezmoi as the permanent user in the normal boot after reviewing its diff.
Select **Workstation Sway** at LightDM; test lock, suspend, portals and KeePassXC
agent add/remove behavior before relying on the new configuration. User home is
shared across recovery snapshots: back up dotfiles separately from root rollback.
The portable clipboard history remains opt-in and package hooks remain disabled.

Clone and review the published source as the permanent user:

```sh
git clone https://github.com/biomlds/sway-chezmoi-portable.git
cd sway-chezmoi-portable
./packages/install.sh --dry-run --tier recommended
chezmoi init --source "$PWD"
chezmoi --source "$PWD" diff
chezmoi --source "$PWD" apply
```

Review the full workstation workflow first, particularly if chezmoi already
manages other dotfiles. These steps apply the chosen clone; publication does not
automatically deploy changes to an installed workstation.
