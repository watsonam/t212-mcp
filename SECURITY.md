# Security

This server can read a brokerage account and place real orders, so I take security problems seriously.

## Reporting a problem

Please don't open a public issue for a security problem. Use GitHub's private reporting instead: go to the Security tab of this repository and choose "Report a vulnerability". Only I can see what you send.

This is a personal project, so a reply may take a few days.

## Which version

Only the latest release, and the latest code on `main`, are supported.

## The official source

The only official sources are [github.com/watsonam/t212-mcp](https://github.com/watsonam/t212-mcp) and the [`t212-mcp` package on PyPI](https://pypi.org/project/t212-mcp/). The PyPI package is only ever built and published from this repository by GitHub Actions, never uploaded by hand. If you see a package or a copy with a similar name somewhere else, it isn't mine, and it could be built to steal your Trading 212 key.

## If your API key may have leaked

1. Open the Trading 212 app, go to Settings, then API, and delete the key straight away.
2. Check your recent orders and account activity.
3. Create a new key, with only the permissions you need, and restrict it to your IP address if the app lets you.
4. Store the new key in your system keychain (see the README), not in a file.
