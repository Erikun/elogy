/*
   This component shows a form for editing a single entry
 */

import React from 'react';
import {Link, Route, Prompt, Switch} from 'react-router-dom';
import update from 'immutability-helper';
import TinyMCEInput from './TinyMCEInput.js';
import {Select, Creatable, AsyncCreatable, Async} from 'react-select';
import Dropzone from 'react-dropzone'
import 'react-select/dist/react-select.css';

import { EntryAttachments } from "./entryattachments.js";
import TINYMCE_CONFIG from "./tinymceconfig.js";
import {withProps} from './util.js';
import { InnerEntry } from "./entry.js";
import "./entryeditor.css";

class EntryAttributeEditor extends React.Component {

    constructor(props) {
        super(props);
        this.state = {
            value: props.value
        }
    }

    onChange (event) {
        this.setState({value: event.target.value});
    }

    onChangeBoolean (event) {
        this.setState({value: event.target.checked});
    }
    
    onChangeSelect (value) {
        this.setState({value: value.value})
    }    

    onChangeMultiSelect (value) {
        this.setState({value: value.map(o => o.value)});
    }

    onBlur () {
        this.props.onChange(this.props.config.name, this.state.value);
    }
    
    makeInputElement () {
        const required = this.props.config.required;
        switch(this.props.config.type) {
            case "text":
                return <input type="text" value={this.state.value}
                              ref="attr" required={required}
                              onChange={this.onChange.bind(this)}
                              onBlur={this.onBlur.bind(this)}/>;
            case "number":
                return <input type="text" value={this.state.value}
                              ref="attr" required={required}
                              onChange={this.onChange.bind(this)}
                              onBlur={this.onBlur.bind(this)}/>;
            case "boolean":
                return <input type="checkbox" checked={this.state.value}
                              ref="attr" required={required}
                              onChange={this.onChangeBoolean.bind(this)}
                              onBlur={this.onBlur.bind(this)}/>;
            case "option":
                return <Creatable value={this.state.value}
                                  required={required}
                                  options={this.props.config.options.map(o => {return {value: o, label: o}})}
                                  onChange={this.onChangeSelect.bind(this)}
                                  onBlur={this.onBlur.bind(this)}/>;
            case "multioption":
                return <Creatable value={this.state.value} multi={true}
                                  required={required}
                                  options={this.props.config.options.map(o => {return {value: o, label: o}})}
                                  onChange={this.onChangeMultiSelect.bind(this)}
                                  onBlur={this.onBlur.bind(this)}/>;
        }
    }
    
    render () {
        const className = `attribute-wrapper ${this.props.config.type}-attribute`;
        return (
            <div className={className}>
                {this.makeInputElement()}
            </div>
        )
    }
}


class EntryEditorBase extends React.Component {

    constructor (props) {
        super(props);
        this.state = {
            submitted: false,

            submitted: false,
            id: null,
            logbook: {},
            title: "",
            authors: [],
            attributes: {},
            attachments: [],
            content: null       
        }
    }

    fetchEntry (logbookId, entryId, fill) {
        fetch(`/api/logbooks/${logbookId}/entries/${entryId}/`,
              {headers: {"Accept": "application/json"}})
            .then(response => response.json())
            .then(json => {
                if (fill)
                    this.setState({entry: json, ...json});
                else
                    this.setState({entry: json});
            });
    }

    fetchLogbook (logbookId) {
        fetch(`/api/logbooks/${logbookId}/`,
              {headers: {"Accept": "application/json"}})
            .then(response => response.json())
            .then(json => this.setState({logbook: json}));        
    }

    onTitleChange (event) {
        this.setState({title: event.target.value});
    }

    fetchUserSuggestions (input) {
        return fetch(`/api/users/`, 
                     {
                         headers: {"Accept": "application/json"}
                     })
            .then(response => response.json())
            .then(response => {return {
                options: (this.state.authors
                              .concat(response.users)),
                complete: false
            }});
    }
    
    onAuthorsChange (newAuthors) {
        this.setState({authors: newAuthors});
    }

    onAttributeChange (name, value) {
        console.log("onAttributeChange", name, value);
        this.setState(update(this.state, {attributes: {[name]: {$set: value}}}));
    }
    
    onContentChange (event) {
        console.log("set content", event.target.getContent());
        this.setState({content: event.target.getContent()});
    }
    
    onAddAttachment (acceptedFiles, rejectedFiles) {
        console.log("drop", acceptedFiles, rejectedFiles);
        this.setState(update({newAttachments: {$push: acceptedFiles}}))
    }
    
    hasEdits () {
        const original = this.state.entry || {};
        return (!this.submitted &&
                (this.state.title != original.title ||
                 this.state.content != original.content ||
                 this.state.authors != original.authors));
    }

    getPromptMessage () {
        /* This is a little confusing, but the <Prompt> component will
           only show a prompt if this function returns a message. */        
        if (this.hasEdits())
            return "Looks like you have made some edits. If you leave, you will lose those...";
    }

    getTitleEditor (title) {
        return (<input type="text" placeholder="title"
                       value={title} required={true}
                       onChange={this.onTitleChange.bind(this)}/>);

    }

    getAuthorsEditor (authors) {
        return <Async
                   name="authors" placeholder="Authors"
                   valueRenderer={o => o.name}
                   multi={true}
                   value={ authors }
                   optionRenderer={o => `${o.login} [${o.name}]`}
                   valueKey="login" labelKey="name"
                   options={ authors }
                   loadOptions={ this.fetchUserSuggestions.bind(this) }
                   onChange={ this.onAuthorsChange.bind(this) }
               />
    }
        
    getContentHTMLEditor (content) {
        return (
            <TinyMCEInput
                value={ content }
                tinymceConfig={ TINYMCE_CONFIG }
                onBlur={ this.onContentChange.bind(this) }/>            
        );
    }

    getAttributes (attributes) {
        return this.state.logbook.attributes?
               this.state.logbook.attributes
                   .map((attr, i) => (
                       <span key={i}>
                           <label>
                               {attr.name}
                               <EntryAttributeEditor
                                   config={attr} 
                                   onChange={this.onAttributeChange.bind(this)}
                                   value={ attributes[attr.name] }/>
                           </label>
                       </span>
                   ))
             : null;
    }

    getAttachments (attachments) {
        return (
            <Dropzone onDrop={this.onAddAttachment.bind(this)}
                      className="attachments-drop">
                Attachments
                <EntryAttachments attachments={ attachments }/>
            </Dropzone>
        );
    }

    getSubmitButton (history) {
        return (
            <button onClick={this.onSubmit.bind(this, history)}>
                Submit
            </button>
        );
    }
        
    getCancelButton () {
        return this.state.entry?
               <Link to={`/logbooks/${this.state.logbook.id}/entries/${this.state.entry.id}`}>
                   Cancel
               </Link> :
               <Link to={`/logbooks/${this.state.logbook.id}/`}>
                   Cancel
               </Link>;
    }

    render () {
        return <Route render={this.renderInner.bind(this)}/>;
    }
}


class EntryEditorNew extends EntryEditorBase {

    componentWillMount () {
        this.fetchLogbook(this.props.match.params.logbookId);
    }
    
    onSubmit({history}) {
        this.submitted = true;
        // we're creating a new entry
        fetch(`/api/logbooks/${this.state.logbook.id}/entries/`, {
            method: "POST",
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                title: this.state.title,
                authors: this.state.authors,
                content: this.state.content || this.state.logbook.template,
                attributes: this.state.attributes
            })
        })
            .then(response => response.json())
        // TODO: handle errors 
            .then(response => {
                // signal other parts of the app that the logbook needs refreshing
                this.props.eventbus.publish("logbook.reload",
                                            this.state.logbook.id);
                // send the browser to view the new entry
                history.push(`/logbooks/${this.state.logbook.id}/entries/${response.id}`);
            });
    }
    
    renderInner (history) {
        
        if (!this.state.logbook)
            return <div>Loading...</div>;
        
        return (
            <div id="entryeditor">

                <Prompt message={this.getPromptMessage.bind(this)}/>
                
                <header>
                    <span className="title">
                        New entry in <span className="logbook"> <i className="fa fa-book"/> {this.state.logbook.name || "ehe"}</span>
                    </span>

                    { this.getTitleEditor(this.state.title) }

                    { this.getAuthorsEditor(this.state.authors) }
                    
                    <div className="attributes">
                        { this.getAttributes(this.state.attributes) }
                    </div>
                    
                </header>
                <div className="content">
                    { this.getContentHTMLEditor(this.state.content ||
                                                this.state.logbook.template || "") }
                </div>
                <footer>
                    { this.getAttachments(this.state.attachments) }
                    { this.getSubmitButton(history) }
                    <div className="commands">
                        { this.getCancelButton() }
                    </div>
                </footer>
            </div>
        );        
    }
}



class EntryEditorFollowup extends EntryEditorBase {

    componentWillMount () {
        this.fetchEntry(this.props.match.params.logbookId,
                        this.props.match.params.entryId);
        this.fetchLogbook(this.props.match.params.logbookId);        
    }
    
    onSubmit({history}) {
        this.submitted = true;
        // we're creating a new entry
        fetch(`/api/logbooks/${this.state.logbook.id}/entries/${this.state.entry.id}/`, {
            method: "POST",
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                title: this.state.entry.title,
                authors: this.state.authors || this.state.entry.authors,
                content: this.state.content || this.state.logbook.template,
                attributes: this.state.attributes
            })
        })
            .then(response => response.json())
        // TODO: handle errors 
            .then(response => {
                // signal other parts of the app that the logbook needs refreshing
                this.props.eventbus.publish("logbook.reload",
                                            this.state.logbook.id);
                // send the browser to view the new entry
                history.push(`/logbooks/${this.state.logbook.id}/entries/${response.id}`);
            });
    }
    
    renderInner (history) {
        
        if (!this.state.logbook || !this.state.entry)
            return <div>Loading...</div>;
        
        return (
            <div id="entryeditor">

                <Prompt message={this.getPromptMessage.bind(this)}/>

                <span className="title">
                    Followup to { this.state.entry.title } in <span className="logbook"> <i className="fa fa-book"/> {this.state.logbook.name || "ehe"}</span>
                </span>                    
                
                <div className="entry">
                    <InnerEntry {...this.state.entry}/>
                </div>
                
                <header>
                    
                    { this.getAuthorsEditor(this.state.authors || this.state.entry.authors) }
                    
                    <div className="attributes">
                        { this.getAttributes(this.state.attributes || this.state.entry.attributes) }
                    </div>
                    
                </header>
                <div className="content">
                    { this.getContentHTMLEditor(this.state.content ||
                                                this.state.logbook.template || "") }
                </div>
                <footer>
                    { this.getAttachments(this.state.attachments ||
                                          this.state.entry.attachments) }
                    { this.getSubmitButton(history) }
                    <div className="commands">
                        { this.getCancelButton() }
                    </div>
                </footer>
            </div>
        );        
    }
}



class EntryEditorEdit extends EntryEditorBase {

    componentWillMount () {
        this.fetchLogbook(this.props.match.params.logbookId);
        this.fetchEntry(this.props.match.params.logbookId,
                        this.props.match.params.entryId, true);
    }
    
    onSubmit({history}) {
        this.submitted = true;
        // we're creating a new entry
        fetch(`/api/logbooks/${this.state.logbook.id}/entries/${this.state.entry.id}/`, {
            method: "PUT",
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                title: this.state.title,
                authors: this.state.authors,
                content: this.state.content, 
                attributes: this.state.attributes,
                revision_n: this.state.entry.revision_n  // must be included for edits!
            })
        })
            .then(response => response.json())
        // TODO: handle errors 
            .then(response => {
                // signal other parts of the app that the logbook needs refreshing
                this.props.eventbus.publish("logbook.reload",
                                            this.state.logbook.id);
                // send the browser to view the new entry
                history.push(`/logbooks/${this.state.logbook.id}/entries/${this.state.entry.id}/`);
            });
    }
    
    renderInner (history) {
        
        if (!(this.state.logbook && this.state.entry))
            return <div>Loading...</div>;

        return (
            <div id="entryeditor">

                <Prompt message={this.getPromptMessage.bind(this)}/>
                
                <header>
                    <span className="title">
                        Editing { this.state.entry.title } in <span className="logbook"> <i className="fa fa-book"/> {this.state.logbook.name || "ehe"}</span>
                    </span>

                    { this.getTitleEditor(this.state.title) }

                    { this.getAuthorsEditor(this.state.authors) }
                    
                    <div className="attributes">
                        { this.getAttributes(this.state.attributes) }
                    </div>
                    
                </header>
                <div className="content">
                    <TinyMCEInput
                        value={ this.state.content || this.state.entry.content }
                        tinymceConfig={ TINYMCE_CONFIG }
                        onBlur={ this.onContentChange.bind(this) }/>
                </div>
                <footer>
                    { this.getAttachments(this.state.attachments) }
                    { this.getSubmitButton(history) }
                    <div className="commands">
                        { this.getCancelButton() }
                    </div>
                </footer>
            </div>
        );        
    }
    
}



class EntryEditor extends React.Component {

    /* just a dummy component that routes to the correct editor */
    
    render () {
        return (
            <Switch>
                <Route path="/logbooks/:logbookId/entries/new" 
                       component={withProps(EntryEditorNew, this.props)}/>
                <Route path="/logbooks/:logbookId/entries/:entryId/new" 
                       component={withProps(EntryEditorFollowup, this.props)}/>
                <Route path="/logbooks/:logbookId/entries/:entryId/edit" 
                       component={withProps(EntryEditorEdit, this.props)}/>            
            </Switch>
        );
    }
    
}


export default EntryEditor;
    
