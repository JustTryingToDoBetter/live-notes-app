<?php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Facades\Redis;
use App\Models\Note;


class NoteController extends Controller
{
    // Retrieve all notes
    public function index()
    {
        return Cache::remember(
            'notes.all',
            30,
            fn() => Note::latest()->get()
        );
    }
    // Store a newly created note
    public function store(Request $request){
        $note = Note::create($request->validate([
            'title'=>'required|string',
            'content'=>'required|string'
        ]));
        Cache::forget('notes.all');
        Redis::publish('notes.created', json_encode($note));
        return response()->json($note, 201);
    }


}
