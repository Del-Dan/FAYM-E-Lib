// ==========================================
// FAYM E-Library: Automation Script
// ==========================================

// === CONFIGURATION ===
// 1. Paste your Dropbox Access Token inside the quotes.
// 2. Paste your Wigal API Key inside the quotes.
const DROPBOX_ACCESS_TOKEN = 'PASTE_DROPBOX_TOKEN_HERE'; 
const SMS_API_KEY = 'PASTE_WIGAL_API_KEY_HERE'; 

// Constants
const DROPBOX_FOLDER_PATH = '/BHL'; 
const SHEET_NAME = 'Dropbox File List';
const METADATA_BATCH_SIZE = 50; 
const SMS_SENDER_ID = 'DelDan'; // Must match your registered Sender ID
const SMS_USERNAME = 'StartApps'; // Required for V3 (Add your username if different)

// Property Keys (Do not change)
const PROP_CURSOR = 'DROPBOX_CURSOR';
const PROP_METADATA_DONE = 'DROPBOX_METADATA_DONE';
const PROP_COVER_ROW = 'DROPBOX_COVER_ROW';
const PROP_LINK_ROW = 'DROPBOX_LINK_ROW';

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('FAYM Imports')
    .addItem('1. Start Metadata Fetch', 'startMetadataFetch')
    .addItem('2. Fetch Shareable Links (Required for Import)', 'startLinkFetch')
    .addItem('3. Fetch Cover URLs (Auto)', 'startCoverFetch')
    .addSeparator()
    .addItem('Install Notification Triggers', 'installTrigger')
    .addToUi();
}

function checkConfig() {
  if (DROPBOX_ACCESS_TOKEN.includes('PASTE') || SMS_API_KEY.includes('PASTE')) {
    SpreadsheetApp.getUi().alert('⚠️ CONFIG ERROR:\nPlease open "Extensions > Apps Script" and paste your real Tokens in the CONFIGURATION section.');
    return false;
  }
  return true;
}

// =========================================
//  PART 1: DROPBOX IMPORTS
// =========================================

function startMetadataFetch() {
  if (!checkConfig()) return;
  PropertiesService.getScriptProperties().deleteProperty(PROP_CURSOR);
  PropertiesService.getScriptProperties().deleteProperty(PROP_METADATA_DONE);
  removeTriggersFor('runMetadataBatch');
  runMetadataBatch();
}

function runMetadataBatch() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME);

  if (!PropertiesService.getScriptProperties().getProperty(PROP_CURSOR) && !PropertiesService.getScriptProperties().getProperty(PROP_METADATA_DONE)) {
    sheet.clearContents();
    sheet.appendRow(['Title', 'Author', 'Keywords', 'Cover URL', 'Shareable Link', 'Dropbox Path', 'Original Filename']);
    sheet.setFrozenRows(1);
    sheet.getRange(1, 1, 1, 7).setFontWeight('bold').setBackground('#f3f4f6');
  }

  const authHeaders = { 'Authorization': 'Bearer ' + DROPBOX_ACCESS_TOKEN, 'Content-Type': 'application/json' };
  const cursor = PropertiesService.getScriptProperties().getProperty(PROP_CURSOR);
  
  let url = cursor ? 'https://api.dropboxapi.com/2/files/list_folder/continue' : 'https://api.dropboxapi.com/2/files/list_folder';
  let payload = cursor ? { cursor: cursor } : { path: DROPBOX_FOLDER_PATH, recursive: true, include_deleted: false, limit: METADATA_BATCH_SIZE };

  try {
    const resp = UrlFetchApp.fetch(url, { method: 'post', headers: authHeaders, payload: JSON.stringify(payload), muteHttpExceptions: true });
    const data = JSON.parse(resp.getContentText());
    
    if (data.error) throw new Error(JSON.stringify(data.error));

    const rows = [];
    for (const item of data.entries || []) {
      if (item['.tag'] !== 'file') continue;
      // Clean Filename
      let title = item.name
        .replace(/\.(pdf|epub|mobi|docx)$/i, '')
        .replace(/_/g, ' ')
        .replace(/-/g, ' ');
        
      rows.push([title, '', '', '', '', item.path_display, item.name]);
    }

    if (rows.length) sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);

    if (data.has_more) {
      PropertiesService.getScriptProperties().setProperty(PROP_CURSOR, data.cursor);
      ScriptApp.newTrigger('runMetadataBatch').timeBased().after(1000).create();
    } else {
      PropertiesService.getScriptProperties().deleteProperty(PROP_CURSOR);
      PropertiesService.getScriptProperties().setProperty(PROP_METADATA_DONE, 'true');
      SpreadsheetApp.getUi().alert('✅ Metadata Fetch Complete!\nNext: Run "Fetch Shareable Links".');
      removeTriggersFor('runMetadataBatch');
    }
  } catch (e) {
    SpreadsheetApp.getUi().alert('❌ Error: ' + e);
    removeTriggersFor('runMetadataBatch');
  }
}

// ---------------------------
// PASS 2: LINKS
// ---------------------------
function startLinkFetch() {
  if (!checkConfig()) return;
  PropertiesService.getScriptProperties().deleteProperty(PROP_LINK_ROW);
  removeTriggersFor('runLinksBatch');
  runLinksBatch();
}

function runLinksBatch() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
  if (!sheet) return;
  
  const lastRow = sheet.getLastRow();
  let startRow = parseInt(PropertiesService.getScriptProperties().getProperty(PROP_LINK_ROW) || '2', 10);
  
  if (lastRow < 2) return;

  const authHeaders = { 'Authorization': 'Bearer ' + DROPBOX_ACCESS_TOKEN, 'Content-Type': 'application/json' };
  let processed = 0;

  for (let row = startRow; row <= lastRow; row++) {
    if (processed >= 20) { // Avoid timeout
      PropertiesService.getScriptProperties().setProperty(PROP_LINK_ROW, String(row));
      ScriptApp.newTrigger('runLinksBatch').timeBased().after(1000).create();
      return; // Hand over to trigger
    }

    const path = sheet.getRange(row, 6).getValue(); // Dropbox Path Column F
    const existingLink = sheet.getRange(row, 5).getValue(); // Link Column E

    if (path && !existingLink) {
       let link = getSharedLink(path, authHeaders);
       if (link) sheet.getRange(row, 5).setValue(link);
    }
    processed++;
  }
  PropertiesService.getScriptProperties().deleteProperty(PROP_LINK_ROW);
  removeTriggersFor('runLinksBatch');
  SpreadsheetApp.getUi().alert('✅ Shareable Links Fetched!');
}

function getSharedLink(path, headers) {
  try {
    // 1. Try Create
    let url = 'https://api.dropboxapi.com/2/sharing/create_shared_link_with_settings';
    let resp = UrlFetchApp.fetch(url, { method: 'post', headers: headers, payload: JSON.stringify({ path: path }), muteHttpExceptions: true });
    let data = JSON.parse(resp.getContentText());
    if (data.url) return data.url;
    
    // 2. Handle Exists Error
    if (data.error && data.error['.tag'] === 'shared_link_already_exists') {
      return data.error.shared_link_already_exists.url;
    }
    
    // 3. Fallback: List
    url = 'https://api.dropboxapi.com/2/sharing/list_shared_links';
    resp = UrlFetchApp.fetch(url, { method: 'post', headers: headers, payload: JSON.stringify({ path: path, direct_only: true }), muteHttpExceptions: true });
    data = JSON.parse(resp.getContentText());
    if (data.links && data.links.length) return data.links[0].url;
    
  } catch (e) { Logger.log(e); }
  return '';
}

// ---------------------------
// PASS 3: COVERS
// ---------------------------
function startCoverFetch() {
  PropertiesService.getScriptProperties().deleteProperty(PROP_COVER_ROW);
  removeTriggersFor('runCoverBatch');
  runCoverBatch();
}

function runCoverBatch() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
  if (!sheet) return;
  const lastRow = sheet.getLastRow();
  let startRow = parseInt(PropertiesService.getScriptProperties().getProperty(PROP_COVER_ROW) || '2', 10);
  
  if (lastRow < 2) return;
  let processed = 0;

  for (let row = startRow; row <= lastRow; row++) {
    if (processed >= 15) {
      PropertiesService.getScriptProperties().setProperty(PROP_COVER_ROW, String(row));
      ScriptApp.newTrigger('runCoverBatch').timeBased().after(1000).create();
      return;
    }
    const title = sheet.getRange(row, 1).getValue();
    const existingCover = sheet.getRange(row, 4).getValue(); // Column D
    if (title && !existingCover) {
        const cover = fetchOpenLibraryCover(title);
        if (cover) sheet.getRange(row, 4).setValue(cover);
    }
    processed++;
    Utilities.sleep(500); // Friendly rate limit
  }
  PropertiesService.getScriptProperties().deleteProperty(PROP_COVER_ROW);
  removeTriggersFor('runCoverBatch');
  SpreadsheetApp.getUi().alert('✅ Covers Fetched (Best Effort)!');
}

function fetchOpenLibraryCover(title) {
  try {
    const resp = UrlFetchApp.fetch(`https://openlibrary.org/search.json?title=${encodeURIComponent(title)}&limit=1`, { muteHttpExceptions: true });
    const data = JSON.parse(resp.getContentText());
    if (data.docs && data.docs.length && data.docs[0].cover_i) {
       return `https://covers.openlibrary.org/b/id/${data.docs[0].cover_i}-L.jpg`; 
    }
  } catch(e) {}
  return null;
}

// =========================================
//  PART 2: NOTIFICATIONS (Email + SMS)
// =========================================

function sendConfirmationEmail(e) {
  // Triggered by Form Submit
  const sheet = e.range.getSheet();
  const values = e.range.getValues()[0]; 
  
  // Update these indices based on your REAL Form columns (0-indexed)
  // Timestamp[0], Email[1], Name[2], Book[3], Phone[4]
  const email = values[1]; 
  const name = values[2];
  const book = values[3];
  const phone = values[4];
  
  if (email && email.includes('@')) {
    MailApp.sendEmail({
      to: email,
      subject: "Book Request Confirmed: " + book,
      body: `Hello ${name},\n\nWe have received your request for "${book}".\nOur team will review it and contact you shortly.\n\nThank you,\nFAYM Library Team`
    });
  }
  
  if (phone) {
     sendConfirmationSMS(phone, `Hi ${name}, request for ${book} received. We will contact you shortly. -FAYM Lib`);
  }
}

function sendConfirmationSMS(phone, message) {
  if (!SMS_API_KEY || SMS_API_KEY.includes('PASTE')) return;

  // Clean Phone Number for Ghana (Common Issue)
  let cleanPhone = String(phone).replace(/\D/g, ''); // Remove non-digits
  if (cleanPhone.length === 10 && cleanPhone.startsWith('0')) {
    cleanPhone = '233' + cleanPhone.substring(1);
  } else if (cleanPhone.length === 9) {
    cleanPhone = '233' + cleanPhone;
  }

  // Uses Wigal Frog V3 API (Verified Working)
  const url = 'https://frogapi.wigal.com.gh/api/v3/sms/send';
  
  const payload = {
    "senderid": SMS_SENDER_ID,
    "destinations": [
      {
        "destination": cleanPhone,
        "msgid": "FAYM_" + Math.floor(Math.random() * 100000)
      }
    ],
    "message": message,
    "smstype": "text"
  };
  
  const headers = {
    'Content-Type': 'application/json',
    'API-KEY': SMS_API_KEY,
    'USERNAME': SMS_USERNAME // Optional if API key is sufficient for some endpoints, but V3 usually likes it.
  };

  try {
    const resp = UrlFetchApp.fetch(url, {
      method: 'post',
      headers: headers,
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });
    Logger.log("SMS Resp: " + resp.getContentText());
  } catch (e) {
    Logger.log('SMS Error: ' + e);
  }
}

function onFormSubmit(e) {
  // Can add logic here to mark book as 'Pending' in inventory if needed
  sendConfirmationEmail(e);
}

function installTrigger() {
  removeTriggersFor('onFormSubmit');
  ScriptApp.newTrigger('onFormSubmit').forSpreadsheet(SpreadsheetApp.getActiveSpreadsheet()).onFormSubmit().create();
  SpreadsheetApp.getUi().alert('✅ Notification Trigger Installed.\nNew form submissions will now trigger Email/SMS.');
}

function removeTriggersFor(handlerName) {
  const triggers = ScriptApp.getProjectTriggers();
  for (const tr of triggers) {
    if (tr.getHandlerFunction() === handlerName) ScriptApp.deleteTrigger(tr);
  }
}
