function// === CONFIG ===
const DROPBOX_FOLDER_PATH = '/BHL'; // Path to your books
const SHEET_NAME = 'Dropbox File List';
const METADATA_BATCH_SIZE = 50; // Smaller batch size for safety
const OPEN_LIBRARY_API = "https://openlibrary.org/search.json";

// === TOKEN (HARDCODED AS REQUESTED) ===
// Paste your token inside the quotes below
const DROPBOX_ACCESS_TOKEN = 'PASTE_YOUR_NEW_DROPBOX_TOKEN_HERE'; 

// === UTIL KEYS ===
const PROP_CURSOR = 'DROPBOX_CURSOR';
const PROP_METADATA_DONE = 'DROPBOX_METADATA_DONE';
const PROP_COVER_ROW = 'DROPBOX_COVER_ROW';

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('FAYM Imports')
    .addItem('1. Start Metadata Fetch', 'startMetadataFetch')
    .addItem('2. Fetch Cover URLs (Auto)', 'startCoverFetch')
    .addToUi();
}

// ---------------------------
// PASS 1: METADATA (batched)
// ---------------------------

function startMetadataFetch() {
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
    // HEADERS REQUIRED BY DJANGO
    sheet.appendRow(['Title', 'Author', 'Keywords', 'Cover URL', 'Dropbox Path', 'Original Filename']);
    sheet.setFrozenRows(1);
  }

  const authHeaders = {
    'Authorization': 'Bearer ' + DROPBOX_ACCESS_TOKEN,
    'Content-Type': 'application/json'
  };

  const cursor = PropertiesService.getScriptProperties().getProperty(PROP_CURSOR);
  let url, payload;
  
  if (!cursor) {
    url = 'https://api.dropboxapi.com/2/files/list_folder';
    payload = { path: DROPBOX_FOLDER_PATH, recursive: true, include_deleted: false, limit: METADATA_BATCH_SIZE };
  } else {
    url = 'https://api.dropboxapi.com/2/files/list_folder/continue';
    payload = { cursor: cursor };
  }

  try {
    const resp = UrlFetchApp.fetch(url, {
      method: 'post',
      headers: authHeaders,
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });
    
    const data = JSON.parse(resp.getContentText());
    if (data.error) throw new Error(JSON.stringify(data.error));

    const rows = [];
    for (const item of data.entries || []) {
      if (item['.tag'] !== 'file') continue;
      
      // DERIVE TITLE FROM FILENAME
      // Remove extension and underscores
      let title = item.name.replace(/\.(pdf|epub|mobi|docx)$/i, '').replace(/_/g, ' ').replace(/-/g, ' ');

      rows.push([
        title,          // Title
        '',             // Author (User to fill)
        '',             // Keywords (User to fill)
        '',             // Cover URL (To be fetched in Pass 2)
        item.path_display,
        item.name
      ]);
    }

    if (rows.length) {
      sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
    }

    if (data.has_more) {
      PropertiesService.getScriptProperties().setProperty(PROP_CURSOR, data.cursor);
      ScriptApp.newTrigger('runMetadataBatch').timeBased().after(1000).create();
    } else {
      PropertiesService.getScriptProperties().deleteProperty(PROP_CURSOR);
      PropertiesService.getScriptProperties().setProperty(PROP_METADATA_DONE, 'true');
      Logger.log('✅ Metadata Complete');
      removeTriggersFor('runMetadataBatch');
      SpreadsheetApp.getUi().alert('Metadata List Complete! Now run "Fetch Cover URLs".');
    }

  } catch (e) {
    Logger.log("Error: " + e);
    removeTriggersFor('runMetadataBatch');
  }
}

// ---------------------------
// PASS 2: COVERS (batched)
// ---------------------------

function startCoverFetch() {
  PropertiesService.getScriptProperties().deleteProperty(PROP_COVER_ROW);
  removeTriggersFor('runCoverBatch');
  runCoverBatch();
}

function runCoverBatch() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET_NAME);
  const lastRow = sheet.getLastRow();
  
  if (lastRow < 2) return;

  // Header is row 1, data starts row 2. Cover URL is Column 4 (D)
  let startRow = parseInt(PropertiesService.getScriptProperties().getProperty(PROP_COVER_ROW), 10);
  if (!startRow || startRow < 2) startRow = 2;

  let processed = 0;
  const BATCH_LIMIT = 15; // API Rate link protection

  for (let row = startRow; row <= lastRow; row++) {
    if (processed >= BATCH_LIMIT) {
      PropertiesService.getScriptProperties().setProperty(PROP_COVER_ROW, String(row));
      ScriptApp.newTrigger('runCoverBatch').timeBased().after(2000).create();
      return;
    }

    const title = sheet.getRange(row, 1).getValue();
    const existingCover = sheet.getRange(row, 4).getValue();

    if (title && !existingCover) {
      const coverUrl = fetchOpenLibraryCover(title);
      if (coverUrl) {
        sheet.getRange(row, 4).setValue(coverUrl);
        // Also try to update Author if found? Optional, let's keep it simple.
      } else {
        sheet.getRange(row, 4).setValue('No Cover Found');
      }
      SpreadsheetApp.flush(); // Save progress visual
    }
    
    processed++;
    Utilities.sleep(500); // Be nice to OpenLibrary API
  }

  PropertiesService.getScriptProperties().deleteProperty(PROP_COVER_ROW);
  removeTriggersFor('runCoverBatch');
  SpreadsheetApp.getUi().alert('Cover Fetch Complete!');
}

function fetchOpenLibraryCover(title) {
  try {
    // Search by title
    const query = encodeURIComponent("title=" + title); // Simple query
    const url = `https://openlibrary.org/search.json?${query}&limit=1`;
    
    const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    const data = JSON.parse(resp.getContentText());

    if (data.docs && data.docs.length > 0) {
       const doc = data.docs[0];
       if (doc.cover_i) {
         return `https://covers.openlibrary.org/b/id/${doc.cover_i}-L.jpg`; 
       }
    }
  } catch (e) {
    Logger.log("API Error for " + title + ": " + e);
  }
  return null;
}

function removeTriggersFor(handlerName) {
  const triggers = ScriptApp.getProjectTriggers();
  for (const tr of triggers) {
    if (tr.getHandlerFunction() === handlerName) ScriptApp.deleteTrigger(tr);
  }
}
  ScriptApp.newTrigger("onFormSubmit")
    .forSpreadsheet(SpreadsheetApp.getActiveSpreadsheet())
    .onFormSubmit()
    .create();
}
