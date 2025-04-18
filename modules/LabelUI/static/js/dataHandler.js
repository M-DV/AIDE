/*
    Maintains the data entries currently on display.

    2019-24 Benjamin Kellenberger
*/

class DataHandler {

    UNDO_STACK_SIZE_LIMIT = 32;     // number of actions to store in undo and redo stacks

    constructor(parentDiv) {
        this.parentDiv = parentDiv;
        this.dataEntries = [];
        this.dataEntryLUT = {};     // entry ID : entry position ordinal
        this.numImagesPerBatch = window.numImagesPerBatch;

        this.actionUndoStack = [];      //TODO: implement DataHandler as action listener and let DataEntry inform handler on user input
        this.actionRedoStack = [];      //TODO: then, implement alternative to _entriesToJSON(false, false) and _jsonToEntries() to only update data entries that have actually changed

        this.prevBatchStack = [];
        this.nextBatchStack = [];

        this.skipConfirmationDialog = window.getCookie('skipAnnotationConfirmation');

        // prepare user statistics (e.g. browser)
        this._navigator = {};
        for (var i in navigator) this._navigator[i] = navigator[i];
        // this._navigator = JSON.stringify(this._navigator);

        // check if user has finished labeling
        if(window.annotationType === 'segmentationMasks') {
            // re-check if finished after every batch in this case
            this.recheckInterval = 1;
        } else {
            this.recheckInterval = Math.max(8, 64 / window.numImagesPerBatch);
        }
        this.numBatchesSeen = 0;
        this._check_user_finished();
    }

    _check_user_finished() {
        let footerPanel = $('#footer-message-panel');
        if(footerPanel.length === 0) return;
        var self = this;
        $.ajax({
            url: 'getUserFinished',
            method: 'GET',
            success: function(response) {
                if(response.hasOwnProperty('finished') && response['finished']) {
                    // show message
                    footerPanel.html('Congratulations, you have finished labeling this dataset!')
                    footerPanel.css('color', 'green');
                    footerPanel.show();

                    // disable querying
                    self.numBatchesSeen = -1;
                } else {
                    // reset counter for querying
                    self.numBatchesSeen = 0;
                }
            }
        });
    }

    freezeActionState() {
        for(var e=0; e<this.dataEntries.length; e++) {
            this.dataEntries[e].freezeActionState();
        }
    }

    resetActionStack() {
        this.actionUndoStack = [];
        this.actionRedoStack = [];
        for(var e=0; e<this.dataEntries.length; e++) {
            this.dataEntries[e].clearActionState();
        }
    }

    onAction(entries, actionName) {
        /**
         * To be called by DataEntry instances. Receives an entry instance or a
         * list of instances and an action name, serializes the entry's/entries'
         * properties and registers them in the action undo stack.
         */
        let actionEntries = {};
        if(Array.isArray(entries)) {
            for(var e=0; e<entries.length; e++) {
                let entry = entries[e];
                actionEntries[entry.entryID] = entry.getActionState();
            }
        } else {
            // single entry
            actionEntries[entries.entryID] = entries.getActionState();
        }
        this.actionUndoStack.push({'action': actionName,
                                   'dataEntries': JSON.stringify(actionEntries)});
    }

    undo() {
        if(this.actionUndoStack.length === 0) return;
        let action = this.actionUndoStack.pop();
        let redoActionEntries = {};
        let dataEntries = JSON.parse(action['dataEntries']);
        for(var key in dataEntries) {
            let entryIdx = this.dataEntryLUT[key];
            if(entryIdx !== undefined) {
                redoActionEntries[key] = this.dataEntries[entryIdx].getActionState();
                this.dataEntries[entryIdx].setProperties(dataEntries[key]);
            }
        }
        this.renderAll();
        this.actionRedoStack.push({'action': action['action'],
                                   'dataEntries': JSON.stringify(redoActionEntries)});
    }

    redo() {
        if(this.actionRedoStack.length === 0) return;
        let action = this.actionRedoStack.pop();
        let undoActionEntries = {};
        let dataEntries = JSON.parse(action['dataEntries']);
        for(var key in dataEntries) {
            let entryIdx = this.dataEntryLUT[key];
            if(entryIdx !== undefined) {
                undoActionEntries[key] = this.dataEntries[entryIdx].getActionState();
                this.dataEntries[entryIdx].setProperties(dataEntries[key]);
            }
        }
        this.renderAll();
        this.actionUndoStack.push({'action': action['action'],
                                   'dataEntries': JSON.stringify(undoActionEntries)});
    }

    get_undo_redo_stats() {
        return {
            'next_undo': this.actionUndoStack.length > 0 ? this.actionUndoStack[this.actionUndoStack.length-1]['action'] : undefined,
            'next_redo': this.actionRedoStack.length > 0 ? this.actionRedoStack[this.actionRedoStack.length-1]['action'] : undefined
        }
    }

    getNumInteractions() {
        let num = 0;
        for(var entry in this.dataEntries) {
            let nextNum = this.dataEntries[entry].numInteractions;
            if(!isNaN(nextNum)) num += nextNum;
        }
        return num;
    }


    renderAll() {
        let promises = this.dataEntries.map((entry) => {
            return entry.render();
        });
        return Promise.all(promises);
    }


    resetZoom() {
        let promises = this.dataEntries.map((entry) => {
            return entry.viewport.resetViewport();
        });
        return Promise.all(promises);
    }


    assignLabelToAll() {
        /*
            For classification entries only: assigns the selected label
            to all data entries.
        */
        if(window.uiBlocked) return;
        this.onAction(this.dataEntries, 'label all');
        for(var i=0; i<this.dataEntries.length; i++) {
            this.dataEntries[i].setLabel(window.labelClassHandler.getActiveClassID(), true);
        }
    }

    clearLabelInAll() {
        /*
            Remove all assigned labels (if 'enableEmptyClass' is true).
        */
        if(window.uiBlocked || !window.enableEmptyClass) return 0;
        this.onAction(this.dataEntries, 'clear all labels');
        var numRemoved = 0;
        for(var i=0; i<this.dataEntries.length; i++) {
            numRemoved += this.dataEntries[i].removeAllAnnotations(true);
        }
        return numRemoved;
    }

    closeActiveSelectionElement() {
        /**
         * Completes an active selection element (e.g., polygon).
         */
        for(var i=0; i<this.dataEntries.length; i++) {
            this.dataEntries[i].closeActiveSelectionElement();
        }
    }

    removeActiveSelectionElements() {
        /**
         * Removes and discards all selection polygons that are active (clicked)
         * if supported (e.g., for semantic segmentation).
         */
        this.onAction(this.dataEntries, 'remove selected');
        for(var i=0; i<this.dataEntries.length; i++) {
            this.dataEntries[i].removeActiveSelectionElements(true);
        }
    }

    removeAllSelectionElements() {
        /**
         * Removes and discards all selection polygons if supported (e.g., for
         * semantic segmentation).
         */
        this.onAction(this.dataEntries, 'remove all selected');
        for(var i=0; i<this.dataEntries.length; i++) {
            this.dataEntries[i].removeAllSelectionElements(true);
        }
    }

    getNumActiveAnnotations() {
        /**
         * Iterates through the data entries and counts the number of
         * annotations that are active. Returns the count accordingly.
         */
        let numActiveAnnotations = 0;
        for(var i=0; i<this.dataEntries.length; i++) {
            numActiveAnnotations += this.dataEntries[i].getNumActiveAnnotations();
        }
        return numActiveAnnotations;
    }

    grabCutOnActiveAnnotations() {
        /**
         * Calls the grabCut routine on each data entry:
         * - if annotation type supports GrabCut (e.g., Polygons) and at least
         *   one annotation is selected: perform GrabCut on it
         * - otherwise, does nothing
         */
        this.freezeActionState();
        let promises = [];
        let self = this;
        for(var i=0; i<this.dataEntries.length; i++) {
            promises.push(this.dataEntries[i].grabCutOnActiveAnnotations(true));
            // this.dataEntries[i].grabCutOnActiveAnnotations();
        }
        return Promise.all(promises).then(() => {
            self.onAction(this.dataEntries, 'Grab Cut');
        });
    }

    refreshActiveAnnotations() {
        /*
            Iterates through the data entries and sets all active annotations
            inactive, unless the globally set active data entry corresponds to
            the respective data entry's entryID.
        */
        for(var i=0; i<this.dataEntries.length; i++) {
            if(this.dataEntries[i].entryID != window.activeEntryID) {
                this.dataEntries[i].setAnnotationsInactive();
            }
        }
    }

    removeActiveAnnotations() {
        if(window.uiBlocked) return 0;
        this.onAction(this.dataEntries, 'remove active');
        var numRemoved = 0;
        if(window.annotationType === 'labels') {
            return this.clearLabelInAll();
        } else {
            for(var i=0; i<this.dataEntries.length; i++) {
                numRemoved += this.dataEntries[i].removeActiveAnnotations(true);
            }
        }
        return numRemoved;
    }

    toggleActiveAnnotationsUnsure() {
        if(window.uiBlocked) return;
        this.onAction(this.dataEntries, 'toggle unsure');
        window.unsureButtonActive = true;   // for classification entries
        var annotationsActive = false;
        for(var i=0; i<this.dataEntries.length; i++) {
            var response = this.dataEntries[i].toggleActiveAnnotationsUnsure(true);
            if(response) annotationsActive = true;
        }
        if(annotationsActive) window.unsureButtonActive = false;
    }

    convertPredictions() {
        if(window.uiBlocked) return;
        this.onAction(this.dataEntries, 'convert predictions');
        for(var i=0; i<this.dataEntries.length; i++) {
            this.dataEntries[i].convertPredictions(true);
        }
    }

    setPredictionsVisible(visible) {
        if(window.uiBlocked) return;
        for(var i=0; i<this.dataEntries.length; i++) {
            this.dataEntries[i].setPredictionsVisible(visible);
        }
    }

    setAnnotationsVisible(visible) {
        if(window.uiBlocked) return;
        for(var i=0; i<this.dataEntries.length; i++) {
            this.dataEntries[i].setAnnotationsVisible(visible);
        }
    }

    setMinimapVisible(visible) {
        if(window.uiBlocked) return;
        for(var i=0; i<this.dataEntries.length; i++) {
            this.dataEntries[i].setMinimapVisible(visible);
        }
    }

    getAllPresentClassIDs() {
        /*
            Returns a dict of all label class IDs that are present
            in the image entry/entries.
        */
        var presentClassIDs = {};
        for(var key in this.dataEntries) {
            presentClassIDs = {...presentClassIDs, ...this.dataEntries[key].getActiveClassIDs()};
        }
        return presentClassIDs;
    }


    updatePresentClasses() {
        //TODO: too much of a mess right now
        // /*
        //     Examines the label classes present in the images and
        //     puts their markup to the top of the class entries.
        // */
        // var presentClassIDs = this.getAllPresentClassIDs();

        // //TODO: this is very expensive; replace with LUT on the long term...
        // var container = $('#legend-entries-active-container');
        // container.empty();
        // for(var key in presentClassIDs) {
        //     container.append(window.labelClassHandler.getClass(key).getMarkup(true));
        // }
    }


    _loadFirstBatch() {
        /**
         * Checks if an image UUID or a list thereof is provided in the URL
         * and loads those image(s) in that case.
         * Else proceeds loading regular batches.
         */
        let url = new URL(window.location.href);
        let uuids_load = url.searchParams.get('imgs');
        if(typeof(uuids_load) === 'string') {
            uuids_load = uuids_load.split(',');

            // make sure image UUIDs are unique
            let uuids_filtered = [];
            let uuids_added = {};
            for(var u=0; u<uuids_load.length; u++) {
                if(!uuids_added.hasOwnProperty(uuids_load[u])) {
                    uuids_filtered.push(uuids_load[u]);
                    uuids_added[uuids_load[u]] = 1;
                }
            }
            return this._loadFixedBatch(uuids_filtered, true);
        } else {
            return this._loadNextBatch();
        }
    }

    _loadNextBatch(cardinalDirection) {
        var self = this;

        var url = 'getLatestImages?order=unlabeled&subset=default&limit=' + this.numImagesPerBatch + '&prefcnn=' + $('#prefered-cnn').val();

        if(typeof(cardinalDirection) === 'string') {
            // get next image in cardinal direction of current tile instead of regular next batch
            if(this.dataEntries.length === 0) {
                return;
            }
            let currentImageID = this.dataEntries[0].entryID;
            url = `getImageCardinalDirection?cd=${cardinalDirection}&ci=${currentImageID}&prefcnn=${$('#prefered-cnn').val()}`;
        }

        return $.ajax({
            url: url,
            dataType: 'json',
            success: function(data) {
                // clear current entries
                if(typeof(cardinalDirection) === 'string' && data.hasOwnProperty('cd')) {
                    // update cardinal direction buttons
                    let numDisabled = 0;
                    let cdBtns = data['cd'];
                    ['w', 'n', 's', 'e'].forEach((x, i) => {
                        $(`#next-button-${x}`).prop('disabled', !cdBtns.hasOwnProperty(x));
                        numDisabled += !cdBtns.hasOwnProperty(x);
                    });
                    
                    if(!data.hasOwnProperty('entries') || Object.keys(data['entries']).length === 0) {
                        // no image in cardinal direction found
                        if(numDisabled === 4) {
                            // project has no registration of cardinal directions; get regular next
                            // batch instead
                            // ugly solution, but works for the time being
                            return self._loadNextBatch();
                        } else {
                            return;
                        }
                    }
                }
                if (data.hasOwnProperty('cnn_stats')){
                    let dropdown = $('#prefered-cnn');
                    let lastValue = dropdown.val();
                    let maxEpochIndex = 0;
                    let maxEpochValue = data['cnn_stats'][0]['pred_count'];
                    dropdown.children().remove();
                    dropdown.append(`<option value="latest">latest : #1 - ${data['cnn_stats'][0]['pred_count']} predictions</option>`);
                    dropdown.append('<option id="max-prediction-option" value="maxPredictions">Max</option>');
                    for (let i = 1; i < data['cnn_stats'].length; i++) {
                        let epoch = data['cnn_stats'][i];
                        dropdown.append(`<option value="${epoch['cnnstate']}">#${i + 1} - ${epoch['pred_count']} predictions</option>`);
                        if (epoch['pred_count'] > maxEpochValue){ maxEpochIndex = i; maxEpochValue = epoch['pred_count']; }
                    }
                    $('#max-prediction-option').html(`Max : #${maxEpochIndex + 1} - ${maxEpochValue} predictions`);
                    var lastValueExists = $('#prefered-cnn option[value="' + lastValue + '"]').length > 0;
                    if (lastValueExists){ dropdown.val(lastValue); }
                    else {dropdown.val("latest");}
                }

                self.parentDiv.empty();
                self.dataEntries = [];

                let imgIDs = '';

                for(var d in data['entries']) {
                    // create new data entry
                    switch(String(window.annotationType)) {
                        case 'labels':
                            var entry = new ClassificationEntry(d, data['entries'][d]);
                            break;
                        case 'points':
                            var entry = new PointAnnotationEntry(d, data['entries'][d]);
                            break;
                        case 'boundingBoxes':
                            var entry = new BoundingBoxAnnotationEntry(d, data['entries'][d]);
                            break;
                        case 'polygons':
                            var entry = new PolygonAnnotationEntry(d, data['entries'][d]);
                            break;
                        case 'segmentationMasks':
                            var entry = new SemanticSegmentationEntry(d, data['entries'][d]);
                            break;
                        default:
                            break;
                    }

                    // append
                    self.parentDiv.append(entry.markup);
                    self.dataEntries.push(entry);
                    
                    imgIDs += d + ','
                }

                self._rebuild_entry_lut();
                self.resetActionStack();

                // update present classes list
                self.updatePresentClasses();

                // show (or hide) predictions depending on threshold
                self.setPredictionsVisible(window.showPredictions_minConf); //TODO: more elegant solution that doesn't require window?
                self.convertPredictions();

                // adjust width of entries
                window.windowResized();

                // re-check if finished (if threshold exceeded)
                if(self.numBatchesSeen >= 0) { 
                    self.numBatchesSeen += 1;
                    if(self.numBatchesSeen >= self.recheckInterval) {
                        // re-check
                        self._check_user_finished();
                    }
                }

                // modify URL
                if(imgIDs.length > 0) {
                    imgIDs = imgIDs.slice(0, imgIDs.length-1);  // remove trailing comma
                    window.history.replaceState({}, document.title, 'interface?imgs=' + imgIDs);
                } else {
                    window.history.replaceState({}, document.title, 'interface');
                }
            },
            error: function(xhr, status, error) {
                if(error == 'Unauthorized') {
                    // ask user to provide password again
                    window.verifyLogin((self._loadNextBatch(cardinalDirection)).bind(self));
                }
            }
        });
    }



    _loadReviewBatch() {
        var self = this;

        // get properties
        var minTimestamp = parseFloat($('#review-timerange').val());
        var skipEmptyImgs = $('#review-skip-empty').prop('checked');
        var goldenQuestionsOnly = $('#review-golden-questions-only').prop('checked');
        var userNames = [];
        if(window.uiControlHandler.hasOwnProperty('reviewUsersTable')) {
            // user is admin; check which names are selected
            window.uiControlHandler.reviewUsersTable.children().each(function() {
                var checked = $(this).find(':checkbox').prop('checked');
                if(checked) {
                    userNames.push($(this).find('.user-list-name').html());
                }
            })
        }

        // get lexicographically newest entry UUID
        let newestEntry = null;
        for(var e=0; e<this.dataEntries.length; e++) {
            if(newestEntry === null || this.dataEntries[e].entryID > newestEntry) {
                newestEntry = this.dataEntries[e].entryID;
            }
        }

        let url = 'getImages_timestamp';
        return $.ajax({
            url: url,
            method: 'POST',
            contentType: "application/json; charset=utf-8",
            dataType: 'json',
            data: JSON.stringify({
                minTimestamp: minTimestamp / 1000.0,
                users: userNames,
                skipEmpty: skipEmptyImgs,
                goldenQuestionsOnly: goldenQuestionsOnly,
                limit: this.numImagesPerBatch,
                lastImageUUID: newestEntry
            }),
            success: function(data) {
                // clear current entries
                self.parentDiv.empty();
                self.dataEntries = [];

                let imgIDs = '';

                for(var d in data['entries']) {
                    // create new data entry
                    switch(String(window.annotationType)) {
                        case 'labels':
                            var entry = new ClassificationEntry(d, data['entries'][d]);
                            break;
                        case 'points':
                            var entry = new PointAnnotationEntry(d, data['entries'][d]);
                            break;
                        case 'boundingBoxes':
                            var entry = new BoundingBoxAnnotationEntry(d, data['entries'][d]);
                            break;
                        case 'segmentationMasks':
                            var entry = new SemanticSegmentationEntry(d, data['entries'][d]);
                            break;
                        default:
                            break;
                    }

                    // append
                    self.parentDiv.append(entry.markup);
                    self.dataEntries.push(entry);

                    // update min and max timestamp
                    var nextTimestamp = data['entries'][d]['last_checked'] * 1000;
                    minTimestamp = Math.max(minTimestamp, nextTimestamp);

                    imgIDs += d + ',';
                }

                self._rebuild_entry_lut();
                self.resetActionStack();

                // update present classes list
                self.updatePresentClasses();

                // show (or hide) predictions depending on threshold
                // self.setPredictionsVisible(window.showPredictions_minConf); //TODO: more elegant solution that doesn't require window?
                self.convertPredictions();

                // update slider and date text
                $('#review-timerange').val(Math.min(parseFloat($('#review-timerange').prop('max')), minTimestamp));
                $('#review-time-text').html(new Date(minTimestamp).toLocaleString());

                // adjust width of entries
                window.windowResized();

                // modify URL
                if(imgIDs.length > 0) {
                    imgIDs = imgIDs.slice(0, imgIDs.length-1);  // remove trailing comma
                    window.history.replaceState({}, document.title, 'interface?imgs=' + imgIDs);
                } else {
                    window.history.replaceState({}, document.title, 'interface');
                }
            },
            error: function(xhr, status, error) {
                if(error == 'Unauthorized') {
                    // ask user to provide password again
                    window.verifyLogin((self._loadReviewBatch).bind(self));
                }
            }
        });
    }


    _entriesToJSON(minimal, onlyUserAnnotations) {
        // assemble entries
        var entries = {};
        for(var e=0; e<this.dataEntries.length; e++) {
            entries[this.dataEntries[e].entryID] = this.dataEntries[e].getProperties(minimal, onlyUserAnnotations);
        }

        // also append client statistics
        var meta = {
            browser: this._navigator,
            windowSize: [$(window).width(), $(window).height()],
            uiControls: {
                burstModeEnabled: window.uiControlHandler.burstMode
            }
        };

        return JSON.stringify({
            'entries': entries,
            'meta': meta
        });
    }


    _jsonToEntries(entries) {
        /**
         * Used to restore previous states e.g. in undo/redo function.
         */
        if(typeof(entries) === 'string') {
            entries = JSON.parse(entries);
        }
        for(var key in entries['entries']) {
            this.dataEntries[this.dataEntryLUT[key]].setProperties(entries['entries'][key]);
        }
        this.renderAll();
    }


    _submitAnnotations(silent) {
        if(window.demoMode) {
            return $.Deferred().promise();
        }

        this.freezeActionState();

        var self = this;
        var entries = this._entriesToJSON(true, false);
        return $.ajax({
            url: 'submitAnnotations',
            type: 'POST',
            contentType: 'application/json; charset=utf-8',
            data: entries,
            dataType: 'json',
            success: function(response) {
                // check status
                if(response['status'] !== 0) {
                    // error
                    if(!silent) {
                        //TODO: make proper messaging system
                        alert('Error: ' + response['message']);
                        return $.Deferred();
                    }
                } else {
                    // submitted; nudge annotation watchdog if possible
                    try {
                        if(window.wfMonitor instanceof WorkflowMonitor) {
                            window.wfMonitor.queryNow(true);
                        }
                    } catch {}
                }
            },
            error: function(xhr, status, error) {
                if(error == 'Unauthorized') {
                    return window.verifyLogin((self._submitAnnotations).bind(self));

                } else {
                    // error
                    if(!silent) {
                        //TODO: make proper messaging system
                        alert('Unexpected error: ' + error);
                        return $.Deferred();
                    }
                }
            }
        });
    }

    reloadCurrentBatch(){
        var entries = [];
        for(var e=0; e<this.dataEntries.length; e++) {
            entries.push(this.dataEntries[e].entryID);
        }
        this._submitAnnotations();
        this._loadFixedBatch(entries, true);
    }

    _loadFixedBatch(batch, applyModelPredictions) {
        let self = this;

        // check if changed and then submit current annotations first
        return $.ajax({
            url: 'getImages',
            contentType: "application/json; charset=utf-8",
            dataType: 'json',
            data: JSON.stringify({'imageIDs':batch, 'prefCNN':$('#prefered-cnn').val()}),
            type: 'POST',
            success: function(data) {
                let imgIDs = '';    // for updating URL in case of errors
                let errors = '';

                if (data.hasOwnProperty('cnn_stats')){
                    let dropdown = $('#prefered-cnn');
                    let lastValue = dropdown.val();
                    let maxEpochIndex = 0;
                    let maxEpochValue = data['cnn_stats'][0]['pred_count'];
                    dropdown.children().remove();
                    dropdown.append(`<option value="latest">latest : #1 - ${data['cnn_stats'][0]['pred_count']} predictions</option>`);
                    dropdown.append('<option id="max-prediction-option" value="maxPredictions">Max</option>');
                    for (let i = 1; i < data['cnn_stats'].length; i++) {
                        let epoch = data['cnn_stats'][i];
                        dropdown.append(`<option value="${epoch['cnnstate']}">#${i + 1} - ${epoch['pred_count']} predictions</option>`);
                        if (epoch['pred_count'] > maxEpochValue){ maxEpochIndex = i; maxEpochValue = epoch['pred_count']; }
                    }
                    $('#max-prediction-option').html(`Max : #${maxEpochIndex + 1} - ${maxEpochValue} predictions`);
                    var lastValueExists = $('#prefered-cnn option[value="' + lastValue + '"]').length > 0;
                    if (lastValueExists){ dropdown.val(lastValue); }
                    else {dropdown.val("latest");}
                }

                // clear current entries
                self.parentDiv.empty();
                self.dataEntries = [];

                // add new ones
                for(var d in batch) {
                    let entryID = batch[d];

                    if(!data['entries'].hasOwnProperty(entryID) || (data.hasOwnProperty('imgs_malformed') && data['imgs_malformed'].hasOwnProperty(entryID))) {
                        errors += entryID + ', ';
                        continue;
                    }

                    switch(String(window.annotationType)) {
                        case 'labels':
                            var entry = new ClassificationEntry(entryID, data['entries'][entryID]);
                            break;
                        case 'points':
                            var entry = new PointAnnotationEntry(entryID, data['entries'][entryID]);
                            break;
                        case 'boundingBoxes':
                            var entry = new BoundingBoxAnnotationEntry(entryID, data['entries'][entryID]);
                            break;
                        case 'polygons':
                            var entry = new PolygonAnnotationEntry(entryID, data['entries'][entryID]);
                            break;
                        case 'segmentationMasks':
                            var entry = new SemanticSegmentationEntry(entryID, data['entries'][entryID]);
                            break;
                        default:
                            break;
                    }

                    // append
                    self.parentDiv.append(entry.markup);
                    self.dataEntries.push(entry);

                    imgIDs += entryID + ',';
                }

                self._rebuild_entry_lut();
                self.resetActionStack();

                // update present classes list
                self.updatePresentClasses();

                if(applyModelPredictions) {
                    // show (or hide) predictions depending on threshold
                    self.setPredictionsVisible(window.showPredictions_minConf); //TODO: more elegant solution that doesn't require window?
                    self.convertPredictions();
                }

                // adjust width of entries
                window.windowResized();

                window.setUIblocked(false);

                // modify URL
                if(imgIDs.length > 0) {
                    imgIDs = imgIDs.slice(0, imgIDs.length-1);  // remove trailing comma
                    window.history.replaceState({}, document.title, 'interface?imgs=' + imgIDs);
                } else {
                    window.history.replaceState({}, document.title, 'interface');
                }

                // show message in case of errors
                if(errors.length > 0) {
                    if(errors.endsWith(', ')) errors = errors.slice(0, errors.length-2);
                    window.messager.addMessage('The following images could not be found or loaded:\n'+errors, 'error');
                }
            },
            error: function(xhr, status, error) {
                if(error == 'Unauthorized') {
                    var callback = function() {
                        self._loadFixedBatch(batch, applyModelPredictions);
                    }
                    window.verifyLogin((callback).bind(self));
                }
            }
        }).then(() => {
            return self.renderAll();
        });
    }

    _rebuild_entry_lut() {
        this.dataEntryLUT = {};
        for(var e=0; e<this.dataEntries.length; e++) {
            this.dataEntryLUT[this.dataEntries[e].entryID] = e;
        }
    }

    nextBatch(cardinalDirection) {
        if(window.uiBlocked) return;

        var self = this;

        if(window.demoMode) {
            var _next_batch = function() {
                // in demo mode we add the entire objects to the history
                for(var e=0; e<self.dataEntries.length; e++) {
                    self.dataEntries[e].markup.detach();
                }
                self.prevBatchStack.push(self.dataEntries.slice());
                if(self.nextBatchStack.length > 0) {
                    // re-initialize stored data entries
                    var entries = self.nextBatchStack.pop();
                    self.dataEntries = entries;
                    for(var e=0; e<self.dataEntries.length; e++) {
                        self.parentDiv.append(self.dataEntries[e].markup);
                    }
                    self._rebuild_entry_lut();
                    self.resetActionStack();
                } else {
                    self._loadNextBatch(cardinalDirection);
                }
            }

        } else {
            var _next_batch = function() {
                // add current image IDs to history
                var historyEntry = [];
                for(var i=0; i<self.dataEntries.length; i++) {
                    historyEntry.push(self.dataEntries[i]['entryID']);
                }
                self.prevBatchStack.push(historyEntry);

                var callback = function() {
                    if(self.nextBatchStack.length > 0) {
                        var nb = self.nextBatchStack.pop();
                        self._loadFixedBatch(nb.slice(), false);
                    } else {
                        //TODO: temporary mode to ensure compatibility with running instances
                        try {
                            if($('#imorder-review').prop('checked') && 
                                typeof(cardinalDirection) !== 'string') {
                                self._loadReviewBatch();
                            } else {
                                self._loadNextBatch(cardinalDirection);
                            }
                        } catch {
                            self._loadNextBatch(cardinalDirection);
                        }
                    }
                };

                // check if annotation commitment is enabled
                var doSubmit = $('#imorder-auto').prop('checked') || $('#review-enable-editing').prop('checked');
                if(doSubmit) {
                    self._submitAnnotations().done(callback);
                } else {
                    // only go to next batch, don't submit annotations
                    callback();
                }
            }
        }
        this._showConfirmationDialog((() => {_next_batch(cardinalDirection)}).bind(this));
    }


    previousBatch() {
        if(window.uiBlocked || this.prevBatchStack.length === 0) return;
        
        var self = this;

        if(window.demoMode) {
            var _previous_batch = function() {
                for(var e=0; e<self.dataEntries.length; e++) {
                    self.dataEntries[e].markup.detach();
                }
                self.nextBatchStack.push(self.dataEntries.slice());

                // re-initialize stored data entries
                var entries = self.prevBatchStack.pop();
                self.dataEntries = entries;
                for(var e=0; e<self.dataEntries.length; e++) {
                    self.parentDiv.append(self.dataEntries[e].markup);
                }
                self._rebuild_entry_lut();
                self.resetActionStack();
            }
        } else {
            var _previous_batch = function() {
                // add current image IDs to history
                var historyEntry = [];
                for(var i=0; i<this.dataEntries.length; i++) {
                    historyEntry.push(this.dataEntries[i]['entryID']);
                }
                this.nextBatchStack.push(historyEntry);
    
                var pb = this.prevBatchStack.pop();

                // check if annotation commitment is enabled
                var doSubmit = $('#imorder-auto').prop('checked') || $('#review-enable-editing').prop('checked');
                if(doSubmit) {
                    this._submitAnnotations().done(function() {
                        self._loadFixedBatch(pb.slice(), false);
                    });
                } else {
                    // only go to next batch, don't submit annotations
                    self._loadFixedBatch(pb.slice(), false);
                }
                // if(dontCommit) {
                //     self._loadFixedBatch(pb.slice());

                // } else {
                //     this._submitAnnotations().done(function() {
                //         self._loadFixedBatch(pb.slice());
                //     });
                // }
            };
        }
        this._showConfirmationDialog((_previous_batch).bind(this));
    }


    _showConfirmationDialog(callback_yes) {
        
        // go to callback directly if user requested not to show message anymore
        if(this.skipConfirmationDialog) {
            callback_yes();
            return;
        }

        // create markup
        if(this.confirmationDialog_markup === undefined) {
            this.confirmationDialog_markup = {};
            this.confirmationDialog_markup.cookieCheckbox = $('<input type="checkbox" style="margin-right:10px" />');
            var cookieLabel = $('<label style="margin-top:20px">Do not show this message again.</label>').prepend(this.confirmationDialog_markup.cookieCheckbox);
            this.confirmationDialog_markup.button_yes = $('<button class="btn btn-primary btn-sm" style="display:inline;float:right">Yes</button>');
            var button_no = $('<button class="btn btn-secondary btn-sm" style="display:inline">No</button>');
            button_no.click(function() {
                window.showOverlay(null);
            });
            var buttons = $('<div></div>').append(button_no).append(this.confirmationDialog_markup.button_yes);
            this.confirmationDialog_markup.markup = $('<div><h2>Confirm annotations</h2><div>Are you satisfied with your annotations?</div></div>').append(cookieLabel).append(buttons);
        }

        // wrap callbacks
        var self = this;
        var dispose = function() {
            // check if cookie is to be set
            var skipMsg = self.confirmationDialog_markup.cookieCheckbox.is(':checked');
            if(skipMsg) {
                window.setCookie('skipAnnotationConfirmation', true, 365);
                self.skipConfirmationDialog = true;
            }
            window.showOverlay(null);
        }
        var action_yes = function() {
            dispose();
            callback_yes();
        }
        this.confirmationDialog_markup.button_yes.click(action_yes);

        window.showOverlay(this.confirmationDialog_markup.markup, false, false);
    }
}