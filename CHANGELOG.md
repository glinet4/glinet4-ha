# Changelog

## [0.4.5](https://github.com/glinet4/glinet4-ha/compare/v0.4.4...v0.4.5) (2026-07-22)


### Features

* add client-count, ethernet-port and USB diagnostic sensors (part of [#30](https://github.com/glinet4/glinet4-ha/issues/30)) ([#54](https://github.com/glinet4/glinet4-ha/issues/54)) ([f93c496](https://github.com/glinet4/glinet4-ha/commit/f93c4961408ff743377f6279196c1453425dfe98))
* add firewall diagnostic entities — WAN exposure, DMZ, port-forward/rule counts (part of [#30](https://github.com/glinet4/glinet4-ha/issues/30)) ([#52](https://github.com/glinet4/glinet4-ha/issues/52)) ([4363654](https://github.com/glinet4/glinet4-ha/commit/43636541298d1c6eb29e85805f196952afaddc2e))
* add multi-WAN and repeater (WiFi-as-WAN) diagnostic sensors ([#57](https://github.com/glinet4/glinet4-ha/issues/57)) ([7e26474](https://github.com/glinet4/glinet4-ha/commit/7e26474daa6d5d36f8b675955e2a853a84116342))
* add per-radio WiFi status diagnostic sensor (part of [#30](https://github.com/glinet4/glinet4-ha/issues/30)) ([#58](https://github.com/glinet4/glinet4-ha/issues/58)) ([a0c8e61](https://github.com/glinet4/glinet4-ha/commit/a0c8e616031bf87461d6be7938562b40f2f46107))
* add WireGuard and OpenVPN server diagnostic sensors (part of [#30](https://github.com/glinet4/glinet4-ha/issues/30)) ([#53](https://github.com/glinet4/glinet4-ha/issues/53)) ([3247d96](https://github.com/glinet4/glinet4-ha/commit/3247d9686fdc79f668d1f91b721f162fdc0069dc))
* create entities dynamically as capabilities appear (Wave E part 1) ([#60](https://github.com/glinet4/glinet4-ha/issues/60)) ([b826e38](https://github.com/glinet4/glinet4-ha/commit/b826e385ff01b27acb8b90265fcb1198e287023c))
* surface DPI top-app traffic as a sensor (part of [#30](https://github.com/glinet4/glinet4-ha/issues/30)) ([#56](https://github.com/glinet4/glinet4-ha/issues/56)) ([b73b4f1](https://github.com/glinet4/glinet4-ha/commit/b73b4f12b69f64d50d449ede25df2bb359f21ccd))


### Bug Fixes

* give an enabled tracked client its own device ([#51](https://github.com/glinet4/glinet4-ha/issues/51)) ([#59](https://github.com/glinet4/glinet4-ha/issues/59)) ([ec3b9a0](https://github.com/glinet4/glinet4-ha/commit/ec3b9a02fff6e7a29e2c3a096bb31873e007e328))

## [0.4.4](https://github.com/glinet4/glinet4-ha/compare/v0.4.3...v0.4.4) (2026-07-20)


### Features

* split polling into four coordinators and make WAN rates readable ([#48](https://github.com/glinet4/glinet4-ha/issues/48)) ([70ebaae](https://github.com/glinet4/glinet4-ha/commit/70ebaae716f4fcfc9f94a98ab71435e89623d189))

## [0.4.3](https://github.com/glinet4/glinet4-ha/compare/v0.4.2...v0.4.3) (2026-07-13)


### Bug Fixes

* render the logo correctly on the HACS page ([#27](https://github.com/glinet4/glinet4-ha/issues/27)) ([c34e543](https://github.com/glinet4/glinet4-ha/commit/c34e543ba4d12855a2402103470608b0c27bba27))

## [0.4.2](https://github.com/glinet4/glinet4-ha/compare/v0.4.1...v0.4.2) (2026-07-12)


### Bug Fixes

* adopt the glinet4 0.2.0 error taxonomy in the config flow ([#25](https://github.com/glinet4/glinet4-ha/issues/25)) ([afd0d82](https://github.com/glinet4/glinet4-ha/commit/afd0d8281aac0d13638a64c2d74f0b7ea3bcecdd))

## [0.4.1](https://github.com/glinet4/glinet4-ha/compare/v0.4.0...v0.4.1) (2026-07-12)


### Bug Fixes

* adopt the glinet4 0.2.0 API (renames, keyword-only mutators) and lift the version cap ([#23](https://github.com/glinet4/glinet4-ha/issues/23)) ([1bf1e94](https://github.com/glinet4/glinet4-ha/commit/1bf1e94cee397a25bd431b4715642f1c99ad50c8))
* cap the glinet4 runtime pin below the upcoming 0.2.0 breaking series ([#21](https://github.com/glinet4/glinet4-ha/issues/21)) ([7455ba2](https://github.com/glinet4/glinet4-ha/commit/7455ba2fcb6ca43428c4d4f5dee7e5fcaa187edd))

## [0.4.0](https://github.com/glinet4/glinet4-ha/compare/v0.3.0...v0.4.0) (2026-07-12)


### Features

* add devcontainer and dev workflow ([#13](https://github.com/glinet4/glinet4-ha/issues/13)) ([a31cc9a](https://github.com/glinet4/glinet4-ha/commit/a31cc9a6cf23aeb2d04892800be31000d1f4c046))
* add entity name and icon translations for all entities ([#4](https://github.com/glinet4/glinet4-ha/issues/4)) ([071ca1b](https://github.com/glinet4/glinet4-ha/commit/071ca1babd0332650162e1b5b7c802cc5ff962c6))


### Bug Fixes

* exclude the release-please CHANGELOG from prettier ([#19](https://github.com/glinet4/glinet4-ha/issues/19)) ([9d744ef](https://github.com/glinet4/glinet4-ha/commit/9d744efdd601b30974361397c2a6403ea3f92b63))
