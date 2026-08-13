# Planning Center setup

ChurchBoard currently connects to Planning Center with a **Personal Access Token (PAT)**. A PAT acts with the permissions of the Planning Center user that created it, so use a deliberately limited account and protect both token values like a password.

Planning Center's official references are [Getting started with the API](https://api.planningcenteronline.com/docs/overview/getting-started), [Authentication](https://api.planningcenteronline.com/docs/overview/authentication), and [Services permissions](https://pcoservices.zendesk.com/hc/en-us/articles/204261964-Permissions-in-Services).

## 1. Prepare a ChurchBoard user

For a shared or permanent installation, the safest arrangement is a dedicated, organization-managed Planning Center user such as `ChurchBoard Integration`. This prevents the dashboard from breaking when a staff member changes roles, leaves, or revokes a personal token.

1. Have a Planning Center organization administrator create or invite the user with an email address your church controls.
2. Give the user access to **Services**, but do not make it an organization administrator.
3. Grant access only to the service types ChurchBoard will display.
4. Use the least privilege that supports the features you enable:

   | ChurchBoard feature | Suggested Planning Center access |
   | --- | --- |
   | Plans, scheduled people, positions, photos, and order of service | Start with **Viewer** for the required Services service types and teams. Test that every required plan and scheduled person is visible. |
   | Advance or control Planning Center Services LIVE | **Editor** for the required service types. |
   | Take LIVE control away from another controller or reset LIVE | **Administrator** for those service types; grant this only if ChurchBoard truly needs it. |
   | Custom unassigned icon from Planning Center media | Permission to view the media item in addition to the Services permissions above. |

5. Secure the user with your organization's normal account-recovery and multi-factor-authentication practices.
6. Record who owns the integration account and review its access periodically.

Planning Center permissions can be scoped by service type. Avoid broad organization-administrator access: ChurchBoard does not need it. If your church does not create dedicated integration users, create the PAT from a stable staff account with the same limited permissions and document who owns it.

## 2. Create a Personal Access Token

Sign in as the user ChurchBoard will use, then:

1. Open Planning Center's [Developer applications page](https://api.planningcenteronline.com/oauth/applications).
2. Find **Personal Access Tokens** and create a token named clearly, such as `ChurchBoard – Worship Center Mac`.
3. Copy the token's **Application ID** and **Secret**.
4. Open **Setup & modules** at `http://127.0.0.1:8040/modules`, then choose the **Planning Center Services** module.
5. Enable **Planning Center**, paste the Application ID and Secret, and choose **Save & test connection**.
6. Select the Services service types ChurchBoard should use.
7. Set the automatic plan-selection window, then save settings.

Never put the secret in screenshots, documentation, chat, source code, or Git. If it is exposed, delete or revoke that PAT in Planning Center and create a replacement. Use a separate PAT for each ChurchBoard installation so one device can be revoked without interrupting the others.

ChurchBoard stores the credential only in its local data directory. Review [security guidance](../SECURITY.md) before exposing ChurchBoard beyond a trusted production network.

## 3. Prepare teams, positions, and schedules

ChurchBoard's position filters come from the teams and positions available to the token user. The people shown on a board come from the selected plan's scheduled team members—not from the general People directory.

For each plan:

1. Add the needed teams and positions in Planning Center Services, such as `Band · Vox 1`, `Band · Worship Leader`, or `Production · Audio`.
2. Schedule each person in the correct position for that specific plan.
3. Resolve `Needed` or declined assignments before the service when possible.
4. In ChurchBoard's dashboard editor, select the categories/teams and positions the widget should show, then drag them into display order.
5. In **Setup & modules**, open the Shure or Sennheiser module and map microphones to those same Planning Center positions.

An open selected position appears as **Unassigned**. A scheduled person still appears when the position has no microphone mapping.

## 4. Add and update profile photos

ChurchBoard does not maintain a second photo library. During each Planning Center sync it reads the photo URL from the **person linked to the scheduled team-member record** in the active plan. This keeps the same picture in Planning Center, Church Center, and ChurchBoard.

### Let a person update their own photo in Services

1. Sign in to Planning Center Services.
2. Select the profile picture or initials in the upper-right corner.
3. Choose **My profile**.
4. Select the current avatar and choose **Change photo**.
5. Upload and save a clear portrait.

Planning Center documents this flow in [Update your profile](https://pcoservices.zendesk.com/hc/en-us/articles/204261494-Update-your-profile).

### Let a person update it through Church Center

If your church permits profile editing in Church Center, the person can open their profile, choose the edit action, and replace their profile photo. See Planning Center's [profile-update guide](https://pcopeople.zendesk.com/hc/en-us/articles/360047977093-Help-people-update-their-profile).

A scheduler or administrator with the proper People/Services access can also update a team member's profile. Changes apply to the shared Planning Center person record. ChurchBoard will pick up the updated URL on a later sync; if the browser still shows an older cached picture, refresh the display.

For the best card layout, use a well-lit portrait with the person's face near the center and enough space around the head and shoulders for different widget aspect ratios. A person without a photo uses ChurchBoard's initials treatment.

## 5. Assign song or item leaders

Planning Center Services supports structured **Song and Item Leaders**. Using that field is preferable to typing a leader into an item's description because ChurchBoard can connect the selected person to their scheduled position and mapped microphone.

1. Open the plan in Planning Center Services.
2. Hover over the song or service item.
3. Select the **leader/person** icon for that item.
4. Choose the scheduled person who will lead it.
5. Repeat for every item that should show a leader in ChurchBoard.
6. Use Planning Center's leader display/filter to verify the assignments before the service.

Planning Center also permits assigning a leader by **position**, which is useful in templates because the leader follows whoever is scheduled in that position. See [Planning Center's Song and Item Leaders announcement](https://www.planningcenter.com/changelog/services/new-assign-people-or-positions-to-songs-or-items-in-your-plan-with-song-and-item-leaders). For the most predictable ChurchBoard leader-and-mic result, verify that Planning Center resolves the assignment to the currently scheduled person; if it does not, assign that person directly on the plan item.

ChurchBoard resolves the display in this order:

1. the item's structured Planning Center leader assignment;
2. the leader's scheduled team-member record in the active plan;
3. the microphone mapped to that scheduled Planning Center position.

Therefore, a leader may display without a mic if the person is not scheduled in a mapped position, the position spelling/team differs, or no microphone is mapped. Items with no leader should remain unassigned rather than inheriting a leader from another item.

For older plans without the structured leader field, ChurchBoard can use an item note whose label contains `leader`, or content such as `Leader: Jane Doe`, as a text-only fallback. A fallback name cannot reliably resolve a microphone, so the structured leader assignment is recommended.

## 6. Plan-selection best practices

- Give each service type and plan a clear, stable name.
- Enter accurate service/rehearsal times so ChurchBoard can select the correct plan and estimate item start times.
- Use ChurchBoard's **Open days before**, **Open hours before**, and **Close hours after** settings to limit eligible plans.
- If more than one plan is eligible, verify the active plan from the dashboard hamburger menu.
- For multiple services in one plan, keep all service times current. ChurchBoard chooses the active service instance and uses the earliest service before the day's services begin.

## Troubleshooting

**The connection test fails**

- Re-enter the Application ID and Secret without extra spaces.
- Confirm the PAT has not been revoked.
- Sign in as the PAT user and verify that it can open Services.
- Confirm the ChurchBoard computer can reach `api.planningcenteronline.com`.

**A service type, team, position, or person is missing**

- Confirm the PAT user has access to that service type and team.
- Confirm the person is scheduled and not declined in the selected plan.
- Save and test the Planning Center connection again to refresh catalogs.
- Verify ChurchBoard is displaying the intended plan and service time.

**A photo is missing**

- Open the scheduled person's Planning Center profile and confirm the photo appears there.
- Confirm the scheduled team-member record is linked to that same person.
- Refresh ChurchBoard after the Planning Center change has synchronized.

**The leader or mic is missing**

- Verify the leader on the exact Planning Center item, not only in the song arrangement or description.
- Confirm the leader is scheduled in the active plan.
- Confirm that scheduled position is mapped to the desired mic in ChurchBoard.
- Prefer a direct person assignment if a position-based leader is not resolving as expected.
