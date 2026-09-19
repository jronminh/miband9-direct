# Mi Band 9 command catalogue

Generated from `client/registry.py` (`python -m client.registry`).

Status: **live** verified on the band (fw 2.3.151) · **set** verified state-changing write · **reply** band replied and it was decoded · **known** discovered (app / firmware / Gadgetbridge), not tried here. `in code` marks commands reachable by name from `client/commands.py`.

## Auth (type 1)

| name | T,S | description | payload | status | in code |
|---|---|---|---|---|---|
| `auth-common` | 1,1 | auth-related (app-internal) |  | known |  |
| `auth-user-id-v1` | 1,5 | send user id (legacy flow) |  | known |  |
| `auth-phone-nonce` | 1,26 | login step 1: phone nonce | PhoneNonce{nonce} | live | yes |
| `auth-step3` | 1,27 | login step 3: confirm + devinfo | Auth.authStep3 | live | yes |

## System (type 2)

| name | T,S | description | payload | status | in code |
|---|---|---|---|---|---|
| `battery` | 2,1 | battery level + charging state | none | live | yes |
| `info` | 2,2 | device info: serial, firmware, model | none | live | yes |
| `clock` | 2,3 | set date/time/timezone/24h | system{clock{...}} | live | yes |
| `firmware-install` | 2,5 | firmware install |  | known |  |
| `language` | 2,6 | band UI language | system{language{field1="en_us"}} | live | yes |
| `camera-get` | 2,7 | camera remote state |  | reply |  |
| `camera-set` | 2,8 | camera remote control |  | known |  |
| `password-get` | 2,9 | lock password state |  | reply |  |
| `misc-setting-get` | 2,14 | misc settings (field 35) |  | reply |  |
| `misc-setting-set` | 2,15 | set misc setting |  | known |  |
| `find-phone` | 2,17 | ring the phone |  | known | yes |
| `findwatch` | 2,18 | vibrate the band | system{field4{field5: 0=start,1=stop}} | live | yes |
| `password-set` | 2,21 | set lock password |  | known |  |
| `dnd` | 2,23 | do-not-disturb | system{dndStatus{status: 0=on,2=off}} | live | yes |
| `display-items-get` | 2,29 | menu/display items list |  | reply |  |
| `display-items-set` | 2,30 | set display items |  | known |  |
| `workout-types-get` | 2,39 | workout types |  | known |  |
| `misc-setting-from-band` | 2,42 | misc setting pushed by band |  | known |  |
| `silent-mode-get` | 2,43 | silent mode state |  | known |  |
| `silent-mode-set-phone` | 2,44 | silent mode set from phone |  | known |  |
| `silent-mode-set-watch` | 2,45 | silent mode set from watch |  | known |  |
| `widget-screens-get` | 2,51 | widget screens |  | known |  |
| `widget-screens-set` | 2,52 | set widget screens |  | known |  |
| `widget-parts-get` | 2,53 | widget parts |  | known |  |
| `low-latency` | 2,67 | watchface low-latency mode |  | known |  |
| `state` | 2,78 | device state | none | live | yes |
| `device-state` | 2,79 | device state (set/push) |  | known |  |
| `system-92` | 2,92 | system setting (unknown) |  | known |  |
| `accessibility` | 2,105 | accessibility data |  | known |  |

## Watchface (type 4)

| name | T,S | description | payload | status | in code |
|---|---|---|---|---|---|
| `face-sync` | 4,0 | sync local watchface |  | known |  |
| `face-set-id` | 4,1 | set watchface id |  | known |  |
| `face-delete` | 4,2 | delete watchface |  | known |  |
| `face-remove-photo` | 4,3 | remove face photo |  | known |  |
| `face-preinstall` | 4,4 | pre-install watchface |  | known |  |
| `face-current` | 4,7 | get current watchface |  | known |  |
| `face-list` | 4,10 | list watchfaces |  | known |  |
| `face-request-edit` | 4,11 | request watchface edit |  | known |  |
| `face-get` | 4,14 | get a specified watchface |  | known |  |

## (unknown) (type 5)

| name | T,S | description | payload | status | in code |
|---|---|---|---|---|---|
| `type5-10` | 5,10 | unknown (type 5) |  | known |  |

## Notification (type 7)

| name | T,S | description | payload | status | in code |
|---|---|---|---|---|---|
| `notify` | 7,0 | send a notification | notification{notification2{notification3{...}}} | live | yes |
| `dismiss` | 7,1 | dismiss a notification | NotificationDismiss{NotificationId{id,package}} | live | yes |
| `call-reject` | 7,2 | reject incoming call |  | known |  |
| `call-ignore` | 7,5 | ignore incoming call |  | known |  |
| `screen-on-get` | 7,6 | screen-on-on-notification state |  | reply |  |
| `screen-on-set` | 7,7 | screen-on-on-notification toggle | notification{screenOnOnNotifications=bool} | set | yes |
| `open-on-phone` | 7,8 | open on phone |  | known |  |
| `canned-messages-get` | 7,9 | quick SMS replies |  | reply |  |
| `canned-messages-set` | 7,12 | set quick SMS replies |  | known |  |
| `call-reply-send` | 7,13 | call reply send |  | known |  |
| `call-reply-ack` | 7,14 | call reply ack |  | known |  |
| `notif-icon-request` | 7,15 | notification icon (reply) |  | known |  |
| `notif-icon-query` | 7,16 | band requests notif icon |  | reply |  |

## Health (type 8)

| name | T,S | description | payload | status | in code |
|---|---|---|---|---|---|
| `activity-files-today` | 8,1 | activity file ids (today) | Health{field5{field1:0}} | live | yes |
| `activity-files-past` | 8,2 | activity file ids (past) | none | live | yes |
| `activity-request` | 8,3 | request one activity file by id | Health{field2: file-id} | live | yes |
| `activity-ack` | 8,5 | ack one activity file by id | Health{field3: file-id} | live | yes |
| `spo2-config` | 8,8 | SpO2 config |  | known | yes |
| `heart-rate-config` | 8,10 | heart-rate config |  | known | yes |
| `stress-config` | 8,14 | stress config |  | known | yes |
| `vitality-reminder-get` | 8,21 | get vitality reminder |  | known |  |
| `vitality-reminder-set` | 8,22 | set vitality reminder |  | known |  |
| `vitality-score` | 8,35 | vitality score |  | known | yes |
| `goal-support-target` | 8,42 | update goal support target |  | known |  |
| `goal-current-target` | 8,43 | set current goal target |  | known |  |
| `health-52` | 8,52 | health (unknown) |  | known |  |
| `training-sync` | 8,87 | sync training plan |  | known |  |
| `training-stop` | 8,88 | stop training plan |  | known |  |
| `temperature-get` | 8,101 | get temperature unit |  | known |  |
| `temperature-set` | 8,102 | set temperature unit |  | known |  |

## Weather (type 10)

| name | T,S | description | payload | status | in code |
|---|---|---|---|---|---|
| `weather-0` | 10,0 | weather request |  | known |  |
| `weather-1` | 10,1 | weather request |  | known |  |
| `weather-2` | 10,2 | weather request |  | known |  |
| `weather-3` | 10,3 | weather response |  | known |  |
| `weather-5` | 10,5 | weather response |  | known |  |
| `weather-6` | 10,6 | weather with AccuWeather location | weather{#4{#1{#1 "accu:<id>"}}} | known |  |

## Calendar (type 12)

| name | T,S | description | payload | status | in code |
|---|---|---|---|---|---|
| `calendar` | 12,0 | calendar event |  | known |  |

## Market (type 15)

| name | T,S | description | payload | status | in code |
|---|---|---|---|---|---|
| `market-send` | 15,5 | send market item to watch |  | known |  |

## Schedule (type 17)

| name | T,S | description | payload | status | in code |
|---|---|---|---|---|---|
| `schedule-8` | 17,8 | schedule sync |  | known |  |

## Music (type 18)

| name | T,S | description | payload | status | in code |
|---|---|---|---|---|---|
| `music` | 18,1 | now-playing media info | music{#1{...}} | known | yes |

## Rpk (watch apps) (type 20)

| name | T,S | description | payload | status | in code |
|---|---|---|---|---|---|
| `rpk-list` | 20,0 | list installed watch apps |  | reply |  |
| `rpk-prepare-install` | 20,1 | prepare app install |  | known |  |
| `rpk-uninstall` | 20,3 | uninstall watch app |  | known |  |
| `rpk-launch` | 20,4 | launch watch app |  | known |  |
| `rpk-sync-status` | 20,7 | sync phone-app status |  | known |  |
| `rpk-send-message` | 20,8 | send phone message to app |  | known |  |
| `rpk-wechat-license` | 20,11 | send WeChat license |  | known |  |
| `rpk-wear-app-status` | 20,21 | get wear-app status |  | known |  |

## Phonebook (type 21)

| name | T,S | description | payload | status | in code |
|---|---|---|---|---|---|
| `phonebook` | 21,0 | phonebook |  | known |  |

## DataUpload (type 22)

| name | T,S | description | payload | status | in code |
|---|---|---|---|---|---|
| `data-upload` | 22,0 | file upload (watchface/icon/RPK) | DataUploadRequest{type,md5,size} | known |  |

