# Changelog

## [1.3.1](https://github.com/begna112/vast-monitor/compare/v1.3.0...v1.3.1) (2025-10-26)


### Bug Fixes

* 0 index from troubleshooting in case where config machines &lt; all machines. ([96e4faf](https://github.com/begna112/vast-monitor/commit/96e4faf2d37bbbfc1c7adbf64ad8fc0f5bdc0454))
* attempt to tag the docker image with version. ([d9faa1b](https://github.com/begna112/vast-monitor/commit/d9faa1ba32af36620654c2236e152aa05f8ad9f2))
* handle case where an invalid id for the vast account is in the config. ([869e47b](https://github.com/begna112/vast-monitor/commit/869e47bff3a0bbb9d11a1e3e6124be9b01ec4af2))

## [1.3.0](https://github.com/begna112/vast-monitor/compare/v1.2.0...v1.3.0) (2025-10-20)


### Features

* add docker/compose implementation. ([1e13d7a](https://github.com/begna112/vast-monitor/commit/1e13d7ac2fad9aa35450e9ef2db87461e3531b9d))
* add release version tag for docker builds in GH. ([0006cc6](https://github.com/begna112/vast-monitor/commit/0006cc6ba12f11acccb3737202327456e8110978))
* Improve startup session seeding and multi-target notifications. Include GPU names in startup summaries and service formatters. Allow notification formatters to return multi-message payloads and chunk Discord summaries safely under 2k characters. Capture current rental counters in snapshots and split placeholders across active sessions when seeding rentals. ([de70868](https://github.com/begna112/vast-monitor/commit/de70868c9edf4ce99a79b881d5d741c241319099))
* Initial commit ([5d7d036](https://github.com/begna112/vast-monitor/commit/5d7d036feeae5df2d98c21c23819443df9344143))
* **rentals:** track contract end dates and surface them in notifications ([6e09483](https://github.com/begna112/vast-monitor/commit/6e09483bfd5b18036fa5e521c30b6d6ecfc132e1))


### Bug Fixes

* allow string in machine_maintenance ([ff7c206](https://github.com/begna112/vast-monitor/commit/ff7c2063d2e069c76f17c1730950e893785e1baa))
* fix docker github action ([19baa42](https://github.com/begna112/vast-monitor/commit/19baa42adc3c96648740f65a82199994b90ee1a6))
* for real this time ([6e3c487](https://github.com/begna112/vast-monitor/commit/6e3c48782c81338bf77d8e77891bc9714443b5fa))
* handle case where there are (invalid) machines in the account that aren't in the config. ([3de3e76](https://github.com/begna112/vast-monitor/commit/3de3e76efd8a21a6be549177f9b5811c623514ef))
* Optional geolocation in VastMachine. ([2d20caa](https://github.com/begna112/vast-monitor/commit/2d20caae8c967e76397ae87c5c703d34e325097e))
* pass storage size through as plain float. ([78f7901](https://github.com/begna112/vast-monitor/commit/78f79018a368a0cd2728d434ad380099814070a1))
* Preserve stored sessions across restarts by tightening seeding logic, fix stored pause detection, and surface stored vs running sessions in startup logs/notifications. ([12365e9](https://github.com/begna112/vast-monitor/commit/12365e9d24fcbd5409139b1f371781bff67de259))
* **rentals:** ignore disk-only warnings when storage already released with session ([2a40e17](https://github.com/begna112/vast-monitor/commit/2a40e17b4334e45f18533914bb95aba01d84fed9))
* update VastMachine for machine maintenance fields. ([eb7593e](https://github.com/begna112/vast-monitor/commit/eb7593e5fe6112a769ed77ff707a8f1c544bad9f))
* update version tagging in release-please. ([60dafdb](https://github.com/begna112/vast-monitor/commit/60dafdb4610a3253f86344bc37039e661766d202))

## [1.2.0](https://github.com/begna112/vast-monitor/compare/vast-monitor-v1.1.0...vast-monitor-v1.2.0) (2025-10-04)


### Features

* add release version tag for docker builds in GH. ([0006cc6](https://github.com/begna112/vast-monitor/commit/0006cc6ba12f11acccb3737202327456e8110978))


### Documentation

* major rework of README for ease of use. ([1c0861b](https://github.com/begna112/vast-monitor/commit/1c0861be1b0955f7ed8fc7d43394bf640381acd7))
* Update Python version requirement to 3.12 ([5932075](https://github.com/begna112/vast-monitor/commit/5932075035b9fd6d51efce16a42979f8720f438e))

## [1.1.0](https://github.com/begna112/vast-monitor/compare/vast-monitor-v1.0.0...vast-monitor-v1.1.0) (2025-10-04)


### Features

* add docker/compose implementation. ([1e13d7a](https://github.com/begna112/vast-monitor/commit/1e13d7ac2fad9aa35450e9ef2db87461e3531b9d))
* Improve startup session seeding and multi-target notifications. Include GPU names in startup summaries and service formatters. Allow notification formatters to return multi-message payloads and chunk Discord summaries safely under 2k characters. Capture current rental counters in snapshots and split placeholders across active sessions when seeding rentals. ([de70868](https://github.com/begna112/vast-monitor/commit/de70868c9edf4ce99a79b881d5d741c241319099))
* Initial commit ([5d7d036](https://github.com/begna112/vast-monitor/commit/5d7d036feeae5df2d98c21c23819443df9344143))


### Bug Fixes

* allow string in machine_maintenance ([ff7c206](https://github.com/begna112/vast-monitor/commit/ff7c2063d2e069c76f17c1730950e893785e1baa))
* fix docker github action ([19baa42](https://github.com/begna112/vast-monitor/commit/19baa42adc3c96648740f65a82199994b90ee1a6))
* for real this time ([6e3c487](https://github.com/begna112/vast-monitor/commit/6e3c48782c81338bf77d8e77891bc9714443b5fa))
* handle case where there are (invalid) machines in the account that aren't in the config. ([3de3e76](https://github.com/begna112/vast-monitor/commit/3de3e76efd8a21a6be549177f9b5811c623514ef))
* Preserve stored sessions across restarts by tightening seeding logic, fix stored pause detection, and surface stored vs running sessions in startup logs/notifications. ([12365e9](https://github.com/begna112/vast-monitor/commit/12365e9d24fcbd5409139b1f371781bff67de259))
* update VastMachine for machine maintenance fields. ([eb7593e](https://github.com/begna112/vast-monitor/commit/eb7593e5fe6112a769ed77ff707a8f1c544bad9f))


### Documentation

* Add update instructions to README ([f868d5e](https://github.com/begna112/vast-monitor/commit/f868d5e1d3b85b23c5920d261df808e59a051c7f))
* Update clone URL in installation instructions ([8795e56](https://github.com/begna112/vast-monitor/commit/8795e56d33b4027a0f8806c5741f9b2c41bc755e))
* update readme ([fa3df22](https://github.com/begna112/vast-monitor/commit/fa3df228c95fdc3f515bffb4dd25029fd710d0e6))
* update readme ([5700c3b](https://github.com/begna112/vast-monitor/commit/5700c3bc31b1c4af227858eab905d83bb403ae2e))

# Changelog

All notable changes to this project will be documented in this file. The format is inspired by [Keep a Changelog](https://keepachangelog.com/), and this file is updated automatically by release-please.
