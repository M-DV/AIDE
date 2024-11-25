/**
 * Logic and markup for selecting and modifying tags.
 * 
 * 2024 Benjamin Kellenberger
 */


class Tag {
    constructor(parent,
                id,
                name,
                color,
                checked,
                numImg) {
        this.parent = parent;
        if(id === undefined) {
            id = `tag_temp_${new Date().getTime()}`;
        }
        if(name === undefined) {
            name = 'New Tag';
        }
        this.id = id;
        this.name = name;
        this.color = color;
        this.checked = checked === null || checked === undefined ? false : checked;
        this.numImg = numImg;
    }

    getMarkup(editable, showCheckbox) {
        let self = this;
        let container = $(`<div id="${this.id}"></div>`);
        if(showCheckbox) {
            this.checkbox = $(`<input type="checkbox" />`);
            this.checkbox.prop('checked', this.checked);
            this.checkbox.on('input', function() {
                self.checked = $(this).prop('checked');
                if(self.checked && self.id === 'tag_none') {
                    // deselect other tags
                    self.parent.setChecked(null, false);
                }
                self.parent.trigger('check');
            });
            container.append(this.checkbox);
        }
        let cid = `${this.id}_color`;
        if(!editable) {
            let numImgMarkup = typeof(this.numImg) === 'number' ? ` (${this.numImg} images)` : '';
            container.append($(`<span>${this.name}${numImgMarkup}</span>`));

            // show color as blob
            container.append(this.getTagBlob().clone());
        } else {
            let nameField = $(`<input type="text" value="${this.name}" />`);
            nameField.on('input', function() {
                self.name = $(this).val();
            });
            container.append(nameField);
            if(typeof(this.numImg) === 'number') {
                container.append($(`<span> (${this.numImg} images)</span>`));
            }

            // show color picker
            this.colorElem = $(`<input class="jscolor" data-jscolor="{required:false}" id="${cid}" />`);
            container.append(this.colorElem);
            this.colorpicker = new jscolor(this.colorElem[0]);
            if(this.color !== undefined) {
                this.colorpicker.fromString(this.color);
            }
            this.colorElem.on('change', function() {
                self.color = self.colorpicker.toHEXString();
            });

            // also add delete button
            if(this.id !== 'tag_none') {
                let deleteBtn = $('<button class="btn btn-sm btn-danger">-</button>');
                deleteBtn.on('click', function() {
                    self.parent.removeTag(self.id);
                    container.remove();
                });
                container.append(deleteBtn);
            }
        }
        return container;
    }

    getTagBlob() {
        if(this.tagBlob === undefined) {
            this.tagBlob = $(`<span class="tag-color-blob"
                id="${this.id}" style="background:${this.color}"></span>`);
        }
        return this.tagBlob.clone();
    }

    getData() {
        return {
            'id': this.id,
            'name': this.name,
            'color': this.color,
            'checked': this.checkbox !== undefined ? this.checkbox.prop('checked') : false
        }
    }

    setChecked(checked) {
        this.checkbox.prop('checked', checked);
        this.checked = checked;
    }
}



class TagHandler {
    constructor(parentDiv,
                editable,
                showCheckboxes,
                showNoneOption,
                showNumImages) {
        this.parentDiv = parentDiv;
        this.editable = editable;
        this.showCheckboxes = showCheckboxes;
        this.showNoneOption = showNoneOption;   // for items with no associated tag
        this.showNumImages = showNumImages;
        if(this.showNoneOption) {
            this.noneTag = new Tag(this,
                                   'tag_none',
                                   '(none)',
                                   '#929292',
                                   false);
        }

        this.tags = [];
        this.tag_lut = {};
        this._setup_markup();

        this.events = {
            'check': []
            //TODO: could implement more events, but not needed at the moment
        }
    }

    _setup_markup() {
        let self = this;
        let markup = $('<div></div>');
        if(this.showCheckboxes) {
            this.selectAll = $('<input type="checkbox" id="tags-select-all" />');
            this.selectAll.on('click', function() {
                self.setChecked(null, $(this).prop('checked'));
                self.trigger('check');
            });
            markup.append(this.selectAll);
            markup.append($('<label for="#tags-select-all">all</label>'));
        }
        this.tagContainer = $('<div class="tags-container"></div>');
        markup.append(this.tagContainer);
        if(this.editable) {
            let newTag = $('<button class="btn btn-sm btn-primary">+</button>');
            newTag.on('click', function() {
                self.addTag();
            });
            markup.append(newTag);
        }
        this.parentDiv.append(markup);
    }

    loadTags() {
        let self = this;
        this.removeAllTags();

        if(this.showNoneOption) {
            this.tagContainer.append(this.noneTag.getMarkup(false, this.showCheckboxes));
        }

        return $.ajax({
            url: window.baseURL + 'getTags',
            method: 'GET',
            success: function(data) {
                if(data.hasOwnProperty('tags')) {
                    for(var f=0; f<data['tags'].length; f++) {
                        let tagMeta = data['tags'][f];
                        let tag = new Tag(self,
                                          tagMeta['id'],
                                          tagMeta['name'],
                                          tagMeta['color'],
                                          tagMeta['checked'],
                                          self.showNumImages ? tagMeta['num_img']: undefined);
                        self.tags.push(tag);
                        self.tag_lut[tag.id] = self.tags.length-1;
                        self.tagContainer.append(tag.getMarkup(self.editable, self.showCheckboxes));
                    }
                }
                return self.tags;
            },
            error: function(xhr, status, error) {
                console.error(error);
                if(typeof(xhr) === 'object' && xhr.hasOwnProperty('status') && xhr['status'] !== 401) {
                    window.messager.addMessage('An error occurred while trying to get project tags (message: "' + error + '").', 'error', 0);
                }
            },
            statusCode: {
                401: function(xhr) {
                    return window.renewSessionRequest(xhr, function() {
                        return loadDataManagementSettings();
                    });
                }
            }
        });
    }

    addTag(tagID, name, color, checked) {
        if(tagID === undefined) {
            tagID = `tag_temp_${new Date().getTime()}`;
        }
        if(name === undefined) {
            name = 'New Tag';
        }
        let tag = new Tag(this,
                          tagID,
                          name,
                          color,
                          checked);
        this.tagContainer.append(tag.getMarkup(this.editable, this.showCheckboxes));
        this.tags.push(tag);
        this.tag_lut[tagID] = this.tags.length-1;
    }

    removeTag(tid) {
        if(tid == 'tag_none') return;
        for(var t=0; t<this.tags.length; t++) {
            if(this.tags[t].id === tid) {
                this.tags[t].colorpicker.valueElement = undefined;      //TODO: unlink colorpicker (doesn't fully work at the moment)
                this.tags.splice(t, 1);
                delete this.tag_lut[tid];
                this.tagContainer.find(`#${tid}`).remove();
                return;
            }
        }
        throw Error(`No tag with id "${tid}" found.`);
    }

    removeAllTags() {
        for(var t=0; t<this.tags.length; t++) {
            this.tags[t].colorpicker.valueElement = undefined;      //TODO: unlink colorpicker (doesn't fully work at the moment)
        }
        this.tagContainer.empty();
        this.tags = [];
        this.tag_lut = {};
    }

    saveTags() {
        if(!this.editable) return;
        let self = this;
        let tagDefs = [];
        for(var t=0; t<this.tags.length; t++) {
            tagDefs.push(this.tags[t].getData());
        }
        return $.ajax({
            url: window.baseURL + 'saveTags',
            method: 'POST',
            contentType: 'application/json; charset=utf-8',
            dataType: 'json',
            data: JSON.stringify({
                tags: tagDefs
            }),
            success: function(data) {
                let message = '';
                if(data.hasOwnProperty('tags_new') &&
                    Object.keys(data['tags_new']).length > 0) {
                    message += `Added ${Object.keys(data['tags_new']).length} new tag(s). `
                }
                if(data.hasOwnProperty('tags_edited') &&
                    Object.keys(data['tags_edited']).length > 0) {
                    message += `Edited ${Object.keys(data['tags_edited']).length} tag(s). `
                }
                if(data.hasOwnProperty('tags_deleted') &&
                    Object.keys(data['tags_deleted']).length > 0) {
                    message += `Deleted ${Object.keys(data['tags_deleted']).length} tag(s).`
                }
                if(message.length > 0) {
                    window.messager.addMessage(message);
                }
                return self.loadTags();
            },
            error: function(xhr, status, error) {
                console.error(error);
                window.messager.addMessage('An error occurred while saving tags (message: "'+error+'").', 'error', 0);
            },
            statusCode: {
                401: function(xhr) {
                    return window.renewSessionRequest(xhr, function() {
                        self.saveTags();
                    });
                }
            }
        });
    }

    getCheckedTags() {
        let checked = [];
        if(this.noneTag !== undefined && this.noneTag.checked) {
            checked.push('none');
            return checked;
        }
        for(var t=0; t<this.tags.length; t++) {
            if(this.tags[t].checked) {
                checked.push(this.tags[t].id);
            }
        }
        return checked;
    }

    setChecked(tag_ids, checked) {
        if(tag_ids === null || tag_ids === undefined) {
            // apply to all
            for(var t=0; t<this.tags.length; t++) {
                this.tags[t].setChecked(checked);
            }
            if(this.selectAll !== undefined) {
                this.selectAll.prop('checked', checked);
            }

        } else {
            for(var t=0; t<tag_ids.length; t++) {
                this.tags[this.tag_lut[tag_ids[t]]].setChecked(checked);
            }
        }
    }

    /**
     * Returns a markup of color blobs for given tag IDs.
     * @param {*} tag_ids 
     */
    getTagBlobs(tag_ids) {
        let markup = $('<div class="tag-color-blob-row"></div>');
        for(var t=0; t<tag_ids.length; t++) {
            if(this.tag_lut.hasOwnProperty(tag_ids[t])) {
                let tag = this.tags[this.tag_lut[tag_ids[t]]];
                markup.append(tag.getTagBlob());
            }
        }
        return markup;
    }

    on(eventName, callback) {
        this.events[eventName].push(callback);
    }

    trigger(eventName) {
        let checked = this.getCheckedTags();
        if(this.showNoneOption && !checked.includes('none')) {
            this.noneTag.setChecked(false);
        }
        for(var c=0; c<this.events[eventName].length; c++) {
            this.events[eventName][c](checked);
        }
    }
}
