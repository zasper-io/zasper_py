import React, { useState, useEffect } from 'react';
import { w3cwebsocket as W3CWebSocket } from "websocket";

import { Terminal } from 'xterm';
import './xterm.css'
import { FitAddon } from 'xterm-addon-fit';


export default function TerminalTab(props) {

    interface IClient {
        send: any
    }

    const [client, setClient] = useState<IClient>({ send: () => { } });


    const listAllTerminals = () => {
        // Simple GET request using fetch
        fetch('http://localhost:8888/api/terminals/websocket/1')
            .then(response => response.json())
            .then(
                (data) => {
                    console.log("data");
                    console.log(data);
                },
                (error) => {
                    console.log("error");
                }

            );
    }

    const createTerminal = () => {
        // Simple GET request using fetch
        fetch('http://localhost:8888/api/terminals', {
            method: 'POST'
        })
            .then(response => response.json())
            .then(
                (data) => {
                    console.log("data");
                    console.log(data);
                },
                (error) => {
                    console.log("error");
                }

            );
    }

    const writeX = () => {
        console.log("hello");
    }
    const xtermRef = React.useRef<Terminal>();
    const divRef = React.useRef<HTMLDivElement>(null);

    const startWebSocket = () => {


        var client1 = new W3CWebSocket("ws://127.0.0.1:8888/api/terminals/websocket/" + 1)

        // var client1 = new W3CWebSocket("ws://localhost:8888/api/kernels/" + kernel.id + "/channels?session_id=" + session.id);
        // var client1 = new W3CWebSocket("ws://localhost:8888/ws");

        client1.onopen = () => {
            console.log('WebSocket Client Connected');
        };
        // client1.onmessage = (message) => {
        //     message = JSON.parse(message.data);
        //     if (message.channel === "iopub") {
        //         console.log("IOPub => ", message);
        //         if (message.msg_type === 'execute_result') {
        //             console.log(message.content.data);
        //             toast(message.content.data["text/plain"]);
        //             toast(message.content.data["text/html"]);
        //         }
        //         if (message.msg_type === 'stream') {
        //             console.log(message.content.text);
        //             toast(message.content.text);
        //             toast(message.content.text);
        //         }
        //     }
        //     if (message.channel === "shell") {
        //         console.log("Shell => ", message);
        //     }
        // };
        client1.onclose = () => {
            console.log('disconnected');
        }
        setClient(client1);

    }

    useEffect(() => {
        var client1 = new W3CWebSocket("ws://127.0.0.1:8888/api/terminals/websocket/1");

        const xterm = (xtermRef.current = new Terminal({
            theme: {
              background: '#392e6b',
            },
            fontFamily: 'Monospace'
            
          }));

        xterm.open(divRef.current as HTMLElement);
        const fitAddon = new FitAddon();
        xterm.loadAddon(fitAddon);
        fitAddon.fit();
        xterm.writeln("Welcome to Zasper!");

        // xterm.fit()

        client1.onopen = () => {
            console.log('WebSocket Client Connected');
            // const attachAddon = new AttachAddon(client1);
            // xterm.open(divRef.current as HTMLElement);
            // xterm.write("hi")
            // terminal.loadAddon(attachAddon);

            // client1.send(JSON.stringify(["set_size", 16, 212, 261, 1518]));
            xterm.writeln("Welcome to Zasper!");
        };
        client1.onmessage = (message) => {
            message = JSON.parse(message.data);
            console.log(typeof message[1]);
            if (typeof message[1] === "string" && message[1].length > 1) {
                console.log(message[1].length);
                xterm.write(message[1]);
            } else {

            }
        }

        client1.onclose = () => {
            console.log('disconnected');
        }

        setClient(client1);

        xterm.onData((message) => {
            xterm.write(message);
            let data = ["stdin", message]
            client1.send(JSON.stringify(data));
        })


    }, []);

    return (

        <div className="tab-content">
            <div className={props.data.display}>
                <div>
                    <button type='button' onClick={listAllTerminals}>List All Terminals</button>
                    <button type='button' onClick={createTerminal}>Create Terminal</button>
                    <button type='button' onClick={startWebSocket}>Start WebSocket</button>
                </div>
                <div ref={divRef}></div>
            </div>

        </div>

    );
}

