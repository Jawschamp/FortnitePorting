import bpy
import json
import os
import socket
import threading
import re
import traceback
from math import radians
from enum import Enum
from mathutils import Matrix, Vector, Euler
from io_import_scene_unreal_psa_psk_280 import pskimport, psaimport

bl_info = {
    "name": "Fortnite Porting",
    "author": "Half",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "description": "Blender Server for Fortnite Porting",
    "category": "Import",
}

global import_assets_root
global import_settings

global server

class RigType(Enum):
    DEFAULT = 0
    TASTY = 1

class Log:
    INFO = u"\u001b[36m"
    WARNING = u"\u001b[31m"
    ERROR = u"\u001b[33m"
    RESET = u"\u001b[0m"

    @staticmethod
    def information(message):
        print(f"{Log.INFO}[INFO] {Log.RESET}{message}")

    @staticmethod
    def warning(message):
        print(f"{Log.WARNING}[WARN] {Log.RESET}{message}")
        
    @staticmethod
    def error(message):
        print(f"{Log.WARNING}[ERROR] {Log.RESET}{message}")


class Receiver(threading.Thread):

    def __init__(self, event):
        threading.Thread.__init__(self, daemon=True)
        self.event = event
        self.data = None
        self.socket_server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.keep_alive = True

    def run(self):
        host, port = 'localhost', 24280
        self.socket_server.bind((host, port))
        self.socket_server.settimeout(1.0)
        Log.information(f"FortnitePorting Server Listening at {host}:{port}")

        while self.keep_alive:
            current_data = ""
            try:
                data_string = ""
                while True:
                    socket_data, sender = self.socket_server.recvfrom(4096)
                    if data := socket_data.decode('utf-8'):
                        if data == "FPClientMessageFinished":
                            break
                        if data == "FPClientCheckServer":
                            self.socket_server.sendto("FPServerReceived".encode('utf-8'), sender)
                            continue
                        data_string += data
                current_data = data_string
                self.data = json.loads(data_string)
                self.event.set()
                self.socket_server.sendto("FPServerReceived".encode('utf-8'), sender)
               
            except OSError:
                pass
            except JSONDecodeError:
                print(current_data)
                pass

    def stop(self):
        self.keep_alive = False
        self.socket_server.close()
        Log.information("FortnitePorting Server Closed")


# Name, Slot, Location, *Linear
texture_mappings = {
    ("Diffuse", 0, (-300, -75)),
    ("PetalDetailMap", 0, (-300, -75)),

    ("SpecularMasks", 1, (-300, -125), True),
    ("SpecMap", 1, (-300, -125), True),

    ("Normals", 5, (-300, -175), True),
    ("Normal", 5, (-300, -175), True),
    ("NormalMap", 5, (-300, -175), True),

    ("M", 7, (-300, -225), True),

    ("Emissive", 12, (-300, -325)),
    ("EmissiveTexture", 12, (-300, -325)),
}

# Name, Slot
scalar_mappings = {
    ("RoughnessMin", 3),
    ("Roughness Min", 3),
    ("SpecRoughnessMin", 3),

    ("RoughnessMax", 4),
    ("Roughness Max", 4),
    ("SpecRoughnessMax", 4),

    ("emissive mult", 13),
    ("TH_StaticEmissiveMult", 13),
    ("Emissive", 13),

    ("Emissive_BrightnessMin", 14),

    ("Emissive_BrightnessMax", 15),

    ("Emissive Fres EX", 16),
    ("EmissiveFresnelExp", 16),
}

# Name, Slot, *Alpha
vector_mappings = {
    ("Skin Boost Color And Exponent", 10, 11),

    ("EmissiveColor", 18, 17),
    ("Emissive Color", 18, 17)
}


def import_mesh(path: str, import_mesh: bool = True, reorient_bones: bool = False) -> bpy.types.Object:
    path = path[1:] if path.startswith("/") else path
    mesh_path = os.path.join(import_assets_root, path.split(".")[0] + "_LOD0")

    if os.path.exists(mesh_path + ".psk"):
        mesh_path += ".psk"
    if os.path.exists(mesh_path + ".pskx"):
        mesh_path += ".pskx"

    if not pskimport(mesh_path, bReorientBones=reorient_bones, bImportmesh = import_mesh):
        return None

    return bpy.context.active_object

def import_skel(path: str) -> bpy.types.Object:
    path = path[1:] if path.startswith("/") else path
    mesh_path = os.path.join(import_assets_root, path.split(".")[0])

    if os.path.exists(mesh_path + ".psk"):
        mesh_path += ".psk"
    if os.path.exists(mesh_path + ".pskx"):
        mesh_path += ".pskx"

    if not pskimport(mesh_path, bImportmesh=False):
        return None

    return bpy.context.active_object


def import_texture(path: str) -> bpy.types.Image:
    path, name = path.split(".")
    if existing := bpy.data.images.get(name):
        return existing

    path = path[1:] if path.startswith("/") else path
    texture_path = os.path.join(import_assets_root, path + ".png")

    if not os.path.exists(texture_path):
        return None

    return bpy.data.images.load(texture_path, check_existing=True)

def import_anim(path: str):
    path = path[1:] if path.startswith("/") else path
    anim_path = os.path.join(import_assets_root, path.split(".")[0] + "_SEQ0" + ".psa")

    return psaimport(anim_path)


def import_material(target_slot: bpy.types.MaterialSlot, material_data):
    mat_hash = material_data.get("Hash")
    if existing := imported_materials.get(mat_hash):
        target_slot.material = existing
        return
    
    target_material = target_slot.material
    material_name = material_data.get("MaterialName")
    
    if target_material.name.casefold() != material_name.casefold():
        target_material = bpy.data.materials.new(material_name)
        
    if any(imported_materials.values(), lambda x: x.name == material_name): # Duplicate Names, Different Hashes
        target_material = bpy.data.materials.new(material_name + f"_{hex(abs(mat_hash))[2:]}")
        
    target_slot.material = target_material
    imported_materials[mat_hash] = target_material

    target_material.use_nodes = True
    nodes = target_material.node_tree.nodes
    nodes.clear()
    links = target_material.node_tree.links
    links.clear()

    output_node = nodes.new(type="ShaderNodeOutputMaterial")
    output_node.location = (200, 0)

    shader_node = nodes.new(type="ShaderNodeGroup")
    shader_node.name = "FP Shader"
    shader_node.node_tree = bpy.data.node_groups.get(shader_node.name)

    links.new(shader_node.outputs[0], output_node.inputs[0])

    def texture_parameter(data):
        name = data.get("Name")
        value = data.get("Value")

        if (info := first(texture_mappings, lambda x: x[0].casefold() == name.casefold())) is None:
            return

        _, slot, location, *linear = info

        if slot == 12 and value.endswith("_FX"):
            return

        if (image := import_texture(value)) is None:
            return

        node = nodes.new(type="ShaderNodeTexImage")
        node.image = image
        node.image.alpha_mode = 'CHANNEL_PACKED'
        node.hide = True
        node.location = location

        if slot == 0:
            nodes.active = node

        if linear:
            node.image.colorspace_settings.name = "Linear"

        links.new(node.outputs[0], shader_node.inputs[slot])

    def scalar_parameter(data):
        name = data.get("Name")
        value = data.get("Value")

        if (info := first(scalar_mappings, lambda x: x[0].casefold() == name.casefold())) is None:
            return

        _, slot = info

        shader_node.inputs[slot].default_value = value

    def vector_parameter(data):
        name = data.get("Name")
        value = data.get("Value")

        if (info := first(vector_mappings, lambda x: x[0].casefold() == name.casefold())) is None:
            return

        _, slot, *extra = info

        shader_node.inputs[slot].default_value = (value["R"], value["G"], value["B"], 1)

        if extra[0]:
            try:
                shader_node.inputs[extra[0]].default_value = value["A"]
            except TypeError:
                shader_node.inputs[extra[0]].default_value = int(value["A"])

    for texture in material_data.get("Textures"):
        texture_parameter(texture)

    for scalar in material_data.get("Scalars"):
        scalar_parameter(scalar)

    vectors = material_data.get("Vectors")
    for vector in vectors:
        vector_parameter(vector)

    emissive_slot = shader_node.inputs["Emissive"]
    if (cropped_emissive_info := first(vectors, lambda x: x.get("Name") in ["EmissiveUVs_RG_UpperLeftCorner_BA_LowerRightCorner", "Emissive Texture UVs RG_TopLeft BA_BottomRight"])) and len(emissive_slot.links) > 0:
        emissive_node = emissive_slot.links[0].from_node
        emissive_node.extension = 'CLIP'
        
        cropped_emissive_pos = cropped_emissive_info.get("Value")
        
        cropped_emissive_shader = nodes.new("ShaderNodeGroup")
        cropped_emissive_shader.node_tree = bpy.data.node_groups.get("FP Cropped Emissive")
        cropped_emissive_shader.location = emissive_node.location + Vector((-200, 25))
        cropped_emissive_shader.inputs[0].default_value = cropped_emissive_pos.get('R')
        cropped_emissive_shader.inputs[1].default_value = cropped_emissive_pos.get('G')
        cropped_emissive_shader.inputs[2].default_value = cropped_emissive_pos.get('B')
        cropped_emissive_shader.inputs[3].default_value = cropped_emissive_pos.get('A')
        links.new(cropped_emissive_shader.outputs[0], emissive_node.inputs[0])
                
def merge_skeletons(parts) -> bpy.types.Armature:
    bpy.ops.object.select_all(action='DESELECT')

    merge_parts = []
    constraint_parts = []
    
    # Merge Skeletons
    for part in parts:
        slot = part.get("Part")
        skeleton = part.get("Armature")
        mesh = part.get("Mesh")
        socket = part.get("Socket")
        if slot == "Body":
            bpy.context.view_layer.objects.active = skeleton

        if slot not in {"Hat", "MiscOrTail"} or socket == "Face" or (socket is None and slot == "Hat"):
            skeleton.select_set(True)
            merge_parts.append(part)
        else:
            constraint_parts.append(part)

    bpy.ops.object.join()
    master_skeleton = bpy.context.active_object
    bpy.ops.object.select_all(action='DESELECT')

    # Merge Meshes
    for part in merge_parts:
        slot = part.get("Part")
        mesh = part.get("Mesh")
        if slot == "Body":
            bpy.context.view_layer.objects.active = mesh
        mesh.select_set(True)
            
    bpy.ops.object.join()
    bpy.ops.object.select_all(action='DESELECT')

    # Remove Duplicates and Rebuild Bone Tree
    bone_tree = {}
    for bone in master_skeleton.data.bones:
        try:
            bone_reg = re.sub(".\d\d\d", "", bone.name)
            parent_reg = re.sub(".\d\d\d", "", bone.parent.name)
            bone_tree[bone_reg] = parent_reg
        except AttributeError:
            pass

    bpy.context.view_layer.objects.active = master_skeleton
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.armature.select_all(action='DESELECT')
    bpy.ops.object.select_pattern(pattern="*.[0-9][0-9][0-9]")
    bpy.ops.armature.delete()

    skeleton_bones = master_skeleton.data.edit_bones

    for bone, parent in bone_tree.items():
        if target_bone := skeleton_bones.get(bone):
            target_bone.parent = skeleton_bones.get(parent)
    
    # Manual Bone Tree Fixes
    other_fixes = {
        "L_eye_lid_lower_mid": "faceAttach",
        "L_eye_lid_upper_mid": "faceAttach",
        "R_eye_lid_lower_mid": "faceAttach",
        "R_eye_lid_upper_mid": "faceAttach",
        "dyn_spine_05": "spine_05"
    }
    
    for bone, parent in other_fixes.items():
        if target_bone := skeleton_bones.get(bone):
            target_bone.parent = skeleton_bones.get(parent)
       
    bpy.ops.object.mode_set(mode='OBJECT')     
    
    # Object Constraints w/ Sockets
    for part in constraint_parts:
        #slot = part.get("Part")
        skeleton = part.get("Armature")
        #mesh = part.get("Mesh")
        socket = part.get("Socket")
        if socket is None:
            continue
        
        if socket.casefold() == "hat":
            constraint_object(skeleton, master_skeleton, "head")
        elif socket.casefold() == "tail":
            constraint_object(skeleton, master_skeleton, "pelvis")
        else:
            constraint_object(skeleton, master_skeleton, socket)
        
  
    return master_skeleton

def apply_tasty_rig(master_skeleton: bpy.types.Armature):
    ik_group = master_skeleton.pose.bone_groups.new(name='IKGroup')
    ik_group.color_set = 'THEME01'
    pole_group = master_skeleton.pose.bone_groups.new(name='PoleGroup')
    pole_group.color_set = 'THEME06'
    twist_group = master_skeleton.pose.bone_groups.new(name='TwistGroup')
    twist_group.color_set = 'THEME09'
    face_group = master_skeleton.pose.bone_groups.new(name='FaceGroup')
    face_group.color_set = 'THEME01'
    dyn_group = master_skeleton.pose.bone_groups.new(name='DynGroup')
    dyn_group.color_set = 'THEME07'
    extra_group = master_skeleton.pose.bone_groups.new(name='ExtraGroup')
    extra_group.color_set = 'THEME10'
    master_skeleton.pose.bone_groups[0].color_set = "THEME08"
    master_skeleton.pose.bone_groups[1].color_set = "THEME08"

    bpy.ops.object.mode_set(mode='EDIT')
    edit_bones = master_skeleton.data.edit_bones

    ik_root_bone = edit_bones.new("tasty_root")
    ik_root_bone.parent = edit_bones.get("root")

    # name, head, tail, roll
    # don't rely on other rig bones for creation
    independent_rig_bones = [
        ('hand_ik_r', edit_bones.get('hand_r').head, edit_bones.get('hand_r').tail, edit_bones.get('hand_r').roll),
        ('hand_ik_l', edit_bones.get('hand_l').head, edit_bones.get('hand_l').tail, edit_bones.get('hand_l').roll),

        ('foot_ik_r', edit_bones.get('foot_r').head, edit_bones.get('foot_r').tail, edit_bones.get('foot_r').roll),
        ('foot_ik_l', edit_bones.get('foot_l').head, edit_bones.get('foot_l').tail, edit_bones.get('foot_l').roll),

        ('pole_elbow_r', edit_bones.get('lowerarm_r').head + Vector((0, 0.5, 0)), edit_bones.get('lowerarm_r').head + Vector((0, 0.5, -0.05)), 0),
        ('pole_elbow_l', edit_bones.get('lowerarm_l').head + Vector((0, 0.5, 0)), edit_bones.get('lowerarm_l').head + Vector((0, 0.5, -0.05)), 0),

        ('pole_knee_r', edit_bones.get('calf_r').head + Vector((0, -0.75, 0)), edit_bones.get('calf_r').head + Vector((0, -0.75, -0.05)), 0),
        ('pole_knee_l', edit_bones.get('calf_l').head + Vector((0, -0.75, 0)), edit_bones.get('calf_l').head + Vector((0, -0.75, -0.05)), 0),

        ('index_control_l', edit_bones.get('index_01_l').head, edit_bones.get('index_01_l').tail, edit_bones.get('index_01_l').roll),
        ('middle_control_l', edit_bones.get('middle_01_l').head, edit_bones.get('middle_01_l').tail, edit_bones.get('middle_01_l').roll),
        ('ring_control_l', edit_bones.get('ring_01_l').head, edit_bones.get('ring_01_l').tail, edit_bones.get('ring_01_l').roll),
        ('pinky_control_l', edit_bones.get('pinky_01_l').head, edit_bones.get('pinky_01_l').tail, edit_bones.get('pinky_01_l').roll),

        ('index_control_r', edit_bones.get('index_01_r').head, edit_bones.get('index_01_r').tail, edit_bones.get('index_01_r').roll),
        ('middle_control_r', edit_bones.get('middle_01_r').head, edit_bones.get('middle_01_r').tail, edit_bones.get('middle_01_r').roll),
        ('ring_control_r', edit_bones.get('ring_01_r').head, edit_bones.get('ring_01_r').tail, edit_bones.get('ring_01_r').roll),
        ('pinky_control_r', edit_bones.get('pinky_01_r').head, edit_bones.get('pinky_01_r').tail, edit_bones.get('pinky_01_r').roll),

        ('eye_control_mid', edit_bones.get('head').head + Vector((0, -0.675, 0)), edit_bones.get('head').head + Vector((0, -0.7, 0)), 0),
    ]

    for new_bone in independent_rig_bones:
        edit_bone: bpy.types.EditBone = edit_bones.new(new_bone[0])
        edit_bone.head = new_bone[1]
        edit_bone.tail = new_bone[2]
        edit_bone.roll = new_bone[3]
        edit_bone.parent = edit_bones.get('tasty_root')

    # name, head, tail, roll, parent
    # DO rely on other rig bones for creation
    dependent_rig_bones = [
        ('eye_control_r', edit_bones.get('eye_control_mid').head + Vector((0.0325, 0, 0)), edit_bones.get('eye_control_mid').tail + Vector((0.0325, 0, 0)), 0, "eye_control_mid"),
        ('eye_control_l', edit_bones.get('eye_control_mid').head + Vector((-0.0325, 0, 0)), edit_bones.get('eye_control_mid').tail + Vector((-0.0325, 0, 0)), 0, "eye_control_mid")
    ]

    for new_bone in dependent_rig_bones:
        edit_bone: bpy.types.EditBone = edit_bones.new(new_bone[0])
        edit_bone.head = new_bone[1]
        edit_bone.tail = new_bone[2]
        edit_bone.roll = new_bone[3]
        edit_bone.parent = edit_bones.get(new_bone[4])

    # current, target
    # connect bone tail to target head
    tail_head_connection_bones = [
        ('upperarm_r', 'lowerarm_r'),
        ('upperarm_l', 'lowerarm_l'),
        ('lowerarm_r', 'hand_r'),
        ('lowerarm_l', 'hand_l'),

        ('thigh_r', 'calf_r'),
        ('thigh_l', 'calf_l'),
        ('calf_r', 'foot_ik_r'),
        ('calf_l', 'foot_ik_l'),
    ]

    for edit_bone in tail_head_connection_bones:
        if (parent_bone := edit_bones.get(edit_bone[0])) and (child_bone := edit_bones.get(edit_bone[1])):
            parent_bone.tail = child_bone.head

    # current, target
    # connect bone head to target head
    head_head_connection_bones = [
        ('L_eye_lid_upper_mid', 'L_eye'),
        ('L_eye_lid_lower_mid', 'L_eye'),
        ('R_eye_lid_upper_mid', 'R_eye'),
        ('R_eye_lid_lower_mid', 'R_eye'),
    ]

    for edit_bone in head_head_connection_bones:
        if (parent_bone := edit_bones.get(edit_bone[0])) and (child_bone := edit_bones.get(edit_bone[1])):
            parent_bone.head = child_bone.head


    for edit_bone in tail_head_connection_bones:
        if (parent_bone := edit_bones.get(edit_bone[0])) and (child_bone := edit_bones.get(edit_bone[1])):
            parent_bone.tail = child_bone.head

    # premade ik bones to remove since we're doing stuff from scratch
    remove_bone_names = ['ik_hand_gun', 'ik_hand_r', 'ik_hand_l','ik_hand_root','ik_foot_root', 'ik_foot_r', 'ik_foot_l']
    for remove_bone_name in remove_bone_names:
        if remove_bone := edit_bones.get(remove_bone_name):
            edit_bones.remove(remove_bone)

    # transform bones based off of local transforms instead of global
    transform_bone_names = ['index_control_l', 'middle_control_l', 'ring_control_l', 'pinky_control_l','index_control_r', 'middle_control_r', 'ring_control_r', 'pinky_control_r']
    for transform_bone_name in transform_bone_names:
        if transform_bone := edit_bones.get(transform_bone_name):
            transform_bone.matrix @= Matrix.Translation(Vector((0.025, 0.0, 0.0)))
            transform_bone.parent = edit_bones.get(transform_bone_name.replace("control", "metacarpal"))

    if (lower_lip_bone := edit_bones.get("FACIAL_C_LowerLipRotation")) and (jaw_bone := edit_bones.get("FACIAL_C_Jaw")):
        lower_lip_bone.parent = jaw_bone

    # rotation fixes
    if jaw_bone_old := edit_bones.get('C_jaw'):
        jaw_bone_old.roll = 0
        jaw_bone_old.tail = jaw_bone_old.head + Vector((0, -0.1, 0)) 

    rot_correction_bones_vertical = ["pelvis", "spine_01", "spine_02", "spine_03", "spine_04", "spine_05", "neck_01", "neck_02", "head"]
    for correct_bone in rot_correction_bones_vertical:
        bone = edit_bones.get(correct_bone)
        bone.tail = bone.head + Vector((0, 0, 0.075))

    if (eye_r := edit_bones.get('R_eye')) or (eye_r := edit_bones.get('FACIAL_R_Eye')):
        if eye_r.tail[1] > eye_r.head[1]:
            old_tail = eye_r.tail + Vector((0,0.001,0))
            old_head = eye_r.head + Vector((0,0.001,0)) # minor change to bypass zero-length bone deletion
            eye_r.tail = old_head
            eye_r.head = old_tail

    if (eye_l := edit_bones.get('L_eye')) or (eye_l := edit_bones.get('FACIAL_L_Eye')):
        if eye_l.tail[1] > eye_l.head[1]:
            old_tail = eye_l.tail + Vector((0,0.001,0))
            old_head = eye_l.head + Vector((0,0.001,0)) # minor change to bypass zero-length bone deletion
            eye_l.tail = old_head
            eye_l.head = old_tail

    bpy.ops.object.mode_set(mode='OBJECT')

    pose_bones = master_skeleton.pose.bones

    # bone name, shape object name, scale, *rotation
    # bones that have custom shapes as bones instead of the normal sticks
    custom_shape_bones = [
        ('root', 'RIG_Root', 0.75, (90, 0, 0)),
        ('pelvis', 'RIG_Torso', 2.0, (0, -90, 0)),
        ('spine_01', 'RIG_Hips', 2.1),
        ('spine_02', 'RIG_Hips', 1.8),
        ('spine_03', 'RIG_Hips', 1.6),
        ('spine_04', 'RIG_Hips', 1.8),
        ('spine_05', 'RIG_Hips', 1.2),
        ('neck_01', 'RIG_Hips', 1.0),
        ('neck_02', 'RIG_Hips', 1.0),
        ('head', 'RIG_Hips', 1.6),

        ('clavicle_r', 'RIG_Shoulder', 1.0),
        ('clavicle_l', 'RIG_Shoulder', 1.0),

        ('upperarm_twist_01_r', 'RIG_Forearm', .13),
        ('upperarm_twist_02_r', 'RIG_Forearm', .10),
        ('lowerarm_twist_01_r', 'RIG_Forearm', .13),
        ('lowerarm_twist_02_r', 'RIG_Forearm', .13),
        ('upperarm_twist_01_l', 'RIG_Forearm', .13),
        ('upperarm_twist_02_l', 'RIG_Forearm', .10),
        ('lowerarm_twist_01_l', 'RIG_Forearm', .13),
        ('lowerarm_twist_02_l', 'RIG_Forearm', .13),

        ('thigh_twist_01_r', 'RIG_Tweak', .15),
        ('calf_twist_01_r', 'RIG_Tweak', .13),
        ('calf_twist_02_r', 'RIG_Tweak', .2),
        ('thigh_twist_01_l', 'RIG_Tweak', .15),
        ('calf_twist_01_l', 'RIG_Tweak', .13),
        ('calf_twist_02_l', 'RIG_Tweak', .2),

        ('hand_ik_r', 'RIG_Hand', 2.6),
        ('hand_ik_l', 'RIG_Hand', 2.6),

        ('foot_ik_r', 'RIG_FootR', 1.0),
        ('foot_ik_l', 'RIG_FootL', 1.0, (0, -90, 0)),

        ('thumb_01_l', 'RIG_Thumb', 1.0),
        ('thumb_02_l', 'RIG_Hips', 0.7),
        ('thumb_03_l', 'RIG_Thumb', 1.0),
        ('index_metacarpal_l', 'RIG_MetacarpalTweak', 0.3),
        ('index_01_l', 'RIG_Index', 1.0),
        ('index_02_l', 'RIG_Index', 1.3),
        ('index_03_l', 'RIG_Index', 0.7),
        ('middle_metacarpal_l', 'RIG_MetacarpalTweak', 0.3),
        ('middle_01_l', 'RIG_Index', 1.0),
        ('middle_02_l', 'RIG_Index', 1.3),
        ('middle_03_l', 'RIG_Index', 0.7),
        ('ring_metacarpal_l', 'RIG_MetacarpalTweak', 0.3),
        ('ring_01_l', 'RIG_Index', 1.0),
        ('ring_02_l', 'RIG_Index', 1.3),
        ('ring_03_l', 'RIG_Index', 0.7),
        ('pinky_metacarpal_l', 'RIG_MetacarpalTweak', 0.3),
        ('pinky_01_l', 'RIG_Index', 1.0),
        ('pinky_02_l', 'RIG_Index', 1.3),
        ('pinky_03_l', 'RIG_Index', 0.7),

        ('thumb_01_r', 'RIG_Thumb', 1.0),
        ('thumb_02_r', 'RIG_Hips', 0.7),
        ('thumb_03_r', 'RIG_Thumb', 1.0),
        ('index_metacarpal_r', 'RIG_MetacarpalTweak', 0.3),
        ('index_01_r', 'RIG_Index', 1.0),
        ('index_02_r', 'RIG_Index', 1.3),
        ('index_03_r', 'RIG_Index', 0.7),
        ('middle_metacarpal_r', 'RIG_MetacarpalTweak', 0.3),
        ('middle_01_r', 'RIG_Index', 1.0),
        ('middle_02_r', 'RIG_Index', 1.3),
        ('middle_03_r', 'RIG_Index', 0.7),
        ('ring_metacarpal_r', 'RIG_MetacarpalTweak', 0.3),
        ('ring_01_r', 'RIG_Index', 1.0),
        ('ring_02_r', 'RIG_Index', 1.3),
        ('ring_03_r', 'RIG_Index', 0.7),
        ('pinky_metacarpal_r', 'RIG_MetacarpalTweak', 0.3),
        ('pinky_01_r', 'RIG_Index', 1.0),
        ('pinky_02_r', 'RIG_Index', 1.3),
        ('pinky_03_r', 'RIG_Index', 0.7),

        ('ball_r', 'RIG_Toe', 2.1),
        ('ball_l', 'RIG_Toe', 2.1),

        ('pole_elbow_r', 'RIG_Tweak', 2.0),
        ('pole_elbow_l', 'RIG_Tweak', 2.0),
        ('pole_knee_r', 'RIG_Tweak', 2.0),
        ('pole_knee_l', 'RIG_Tweak', 2.0),

        ('index_control_l', 'RIG_FingerRotR', 1.0),
        ('middle_control_l', 'RIG_FingerRotR', 1.0),
        ('ring_control_l', 'RIG_FingerRotR', 1.0),
        ('pinky_control_l', 'RIG_FingerRotR', 1.0),
        ('index_control_r', 'RIG_FingerRotR', 1.0),
        ('middle_control_r', 'RIG_FingerRotR', 1.0),
        ('ring_control_r', 'RIG_FingerRotR', 1.0),
        ('pinky_control_r', 'RIG_FingerRotR', 1.0),

        ('eye_control_mid', 'RIG_EyeTrackMid', 0.75),
        ('eye_control_r', 'RIG_EyeTrackInd', 0.75),
        ('eye_control_l', 'RIG_EyeTrackInd', 0.75),
    ]

    for custom_shape_bone_data in custom_shape_bones:
        name, shape, scale, *extra = custom_shape_bone_data
        if not (custom_shape_bone := pose_bones.get(name)):
            continue

        custom_shape_bone.custom_shape = bpy.data.objects.get(shape)
        custom_shape_bone.custom_shape_scale_xyz = scale, scale, scale

        if len(extra) > 0 and (rot := extra[0]):
            custom_shape_bone.custom_shape_rotation_euler = [radians(rot[0]), radians(rot[1]), radians(rot[2])]


    # other tweaks by enumeration of pose bones
    jaw_bones = ["C_jaw", "FACIAL_C_Jaw"]
    face_root_bones = ["faceAttach", "FACIAL_C_FacialRoot"]
    for pose_bone in pose_bones:
        if pose_bone.bone_group is None:
            pose_bone.bone_group = extra_group

        if not pose_bone.parent: # root
            pose_bone.use_custom_shape_bone_size = False
            continue

        if pose_bone.name.startswith("eye_control"):
            pose_bone.use_custom_shape_bone_size = False

        if 'dyn_' in pose_bone.name:
            pose_bone.bone_group = dyn_group

        if 'deform_' in pose_bone.name and pose_bone.bone_group_index != 0: # not unused bones
            pose_bone.custom_shape = bpy.data.objects.get('RIG_Tweak')
            pose_bone.custom_shape_scale_xyz = 0.05, 0.05, 0.05
            pose_bone.use_custom_shape_bone_size = False
            pose_bone.bone_group = dyn_group

        if 'twist_' in pose_bone.name:
            pose_bone.custom_shape_scale_xyz = 0.1, 0.1, 0.1
            pose_bone.use_custom_shape_bone_size = False

        if any(["eyelid", "eye_lid_"], lambda x: x.casefold() in pose_bone.name.casefold()):
            pose_bone.bone_group = face_group
            continue

        if pose_bone.name.casefold().endswith("_eye"):
            pose_bone.bone_group = extra_group
            continue

        if "FACIAL" in pose_bone.name or pose_bone.parent.name in face_root_bones or pose_bone.parent.name in jaw_bones:
            pose_bone.custom_shape = bpy.data.objects.get('RIG_FaceBone')
            pose_bone.bone_group = face_group

        if pose_bone.name in jaw_bones:
            pose_bone.bone_group = face_group
            pose_bone.custom_shape = bpy.data.objects.get('RIG_JawBone')
            pose_bone.custom_shape_scale_xyz = 0.1, 0.1, 0.1
            pose_bone.use_custom_shape_bone_size = False

        if pose_bone.name in face_root_bones:
            pose_bone.bone_group = face_group


    defined_group_bones = {
        "upperarm_twist_01_r": twist_group,
        "upperarm_twist_02_r": twist_group,
        "lowerarm_twist_01_r": twist_group,
        "lowerarm_twist_02_r": twist_group,

        "upperarm_twist_01_l": twist_group,
        "upperarm_twist_02_l": twist_group,
        "lowerarm_twist_01_l": twist_group,
        "lowerarm_twist_02_l": twist_group,

        "thigh_twist_01_r": twist_group,
        "calf_twist_01_r": twist_group,
        "calf_twist_02_r": twist_group,

        "thigh_twist_01_l": twist_group,
        "calf_twist_01_l": twist_group,
        "calf_twist_02_l": twist_group,

        "hand_ik_r": ik_group,
        "hand_ik_l": ik_group,

        "foot_ik_r": ik_group,
        "foot_ik_l": ik_group,

        "pole_elbow_r": pole_group,
        "pole_elbow_l": pole_group,
        "pole_knee_r": pole_group,
        "pole_knee_l": pole_group,

        "index_control_r": extra_group,
        "middle_control_r": extra_group,
        "ring_control_r": extra_group,
        "pinky_control_r": extra_group,

        "index_control_l": extra_group,
        "middle_control_l": extra_group,
        "ring_control_l": extra_group,
        "pinky_control_l": extra_group,

        "eye_control_mid": extra_group,
        "eye_control_r": extra_group,
        "eye_control_l": extra_group,

        "thumb_03_r": extra_group,
        "index_03_r": extra_group,
        "middle_03_r": extra_group,
        "ring_03_r": extra_group,
        "pinky_03_r": extra_group,

        "thumb_03_l": extra_group,
        "index_03_l": extra_group,
        "middle_03_l": extra_group,
        "ring_03_l": extra_group,
        "pinky_03_l": extra_group,

        "root": extra_group,
        "ball_r": extra_group,
        "ball_l": extra_group,
        "head": extra_group,
    }

    for bone_name, group in defined_group_bones.items():
        if bone := pose_bones.get(bone_name):
            bone.bone_group = group

    # bone, target, weight
    # copy rotation modifier added to bones
    copy_rotation_bones = [
        ('hand_r', 'hand_ik_r', 1.0),
        ('hand_l', 'hand_ik_l', 1.0),
        ('foot_r', 'foot_ik_r', 1.0),
        ('foot_l', 'foot_ik_l', 1.0),

        ('L_eye_lid_upper_mid', 'L_eye', 0.25),
        ('L_eye_lid_lower_mid', 'L_eye', 0.25),
        ('R_eye_lid_upper_mid', 'R_eye', 0.25),
        ('R_eye_lid_lower_mid', 'R_eye', 0.25),

        ('index_01_l', 'index_control_l', 1.0),
        ('index_02_l', 'index_control_l', 1.0),
        ('index_03_l', 'index_control_l', 1.0),
        ('middle_01_l', 'middle_control_l', 1.0),
        ('middle_02_l', 'middle_control_l', 1.0),
        ('middle_03_l', 'middle_control_l', 1.0),
        ('ring_01_l', 'ring_control_l', 1.0),
        ('ring_02_l', 'ring_control_l', 1.0),
        ('ring_03_l', 'ring_control_l', 1.0),
        ('pinky_01_l', 'pinky_control_l', 1.0),
        ('pinky_02_l', 'pinky_control_l', 1.0),
        ('pinky_03_l', 'pinky_control_l', 1.0),

        ('index_01_r', 'index_control_r', 1.0),
        ('index_02_r', 'index_control_r', 1.0),
        ('index_03_r', 'index_control_r', 1.0),
        ('middle_01_r', 'middle_control_r', 1.0),
        ('middle_02_r', 'middle_control_r', 1.0),
        ('middle_03_r', 'middle_control_r', 1.0),
        ('ring_01_r', 'ring_control_r', 1.0),
        ('ring_02_r', 'ring_control_r', 1.0),
        ('ring_03_r', 'ring_control_r', 1.0),
        ('pinky_01_r', 'pinky_control_r', 1.0),
        ('pinky_02_r', 'pinky_control_r', 1.0),
        ('pinky_03_r', 'pinky_control_r', 1.0),

        ('dfrm_upperarm_r', 'upperarm_r', 1.0),
        ('dfrm_upperarm_l', 'upperarm_l', 1.0),
    ]

    for bone_data in copy_rotation_bones:
        current, target, weight = bone_data
        if not (pose_bone := pose_bones.get(current)):
            continue

        con = pose_bone.constraints.new('COPY_ROTATION')
        con.target = master_skeleton
        con.subtarget = target
        con.influence = weight

        if 'hand_ik' in target or 'foot_ik' in target:
            con.target_space = 'WORLD'
            con.owner_space = 'WORLD'
        elif 'control' in target:
            con.mix_mode = 'OFFSET'
            con.target_space = 'LOCAL_OWNER_ORIENT'
            con.owner_space = 'LOCAL'
        else:
            con.target_space = 'LOCAL_OWNER_ORIENT'
            con.owner_space = 'LOCAL'

    # target, ik, pole
    # do i have to explain thing
    ik_bones = [
        ('lowerarm_r', 'hand_ik_r', 'pole_elbow_r'),
        ('lowerarm_l', 'hand_ik_l', 'pole_elbow_l'),
        ('calf_r', 'foot_ik_r', 'pole_knee_r'),
        ('calf_l', 'foot_ik_l', 'pole_knee_l'),
    ]

    for ik_bone_data in ik_bones:
        target, ik, pole = ik_bone_data
        con = pose_bones.get(target).constraints.new('IK')
        con.target = master_skeleton
        con.subtarget = ik
        con.pole_target = master_skeleton
        con.pole_subtarget = pole
        con.pole_angle = radians(180)
        con.chain_count = 2

    #
    # only gonna be the head but whatever
    track_bones = [
        ('eye_control_mid', 'head', 0.285)
    ]

    for track_bone_data in track_bones:
        current, target, head_tail = track_bone_data
        if not (pose_bone := pose_bones.get(current)):
            continue

        con = pose_bone.constraints.new('TRACK_TO')
        con.target = master_skeleton
        con.subtarget = target
        con.head_tail = head_tail
        con.track_axis = 'TRACK_Y'
        con.up_axis = 'UP_Z'

    # bone, target, ignore axis', axis
    lock_track_bones = [
        ('R_eye', 'eye_control_r', ['Y']),
        ('L_eye', 'eye_control_l', ['Y']),
        ('FACIAL_R_Eye', 'eye_control_r', ['Y']),
        ('FACIAL_L_Eye', 'eye_control_l', ['Y']),
    ]

    for lock_track_bone_data in lock_track_bones:
        current, target, ignored = lock_track_bone_data
        if not (pose_bone := pose_bones.get(current)):
            continue

        for axis in ['X', 'Y', 'Z']:
            if axis in ignored:
                continue
            con = pose_bone.constraints.new('LOCKED_TRACK')
            con.target = master_skeleton
            con.subtarget = target
            con.track_axis = 'TRACK_Y'
            con.lock_axis = 'LOCK_' + axis

    bones = master_skeleton.data.bones

    hide_bones = ['hand_r', 'hand_l', 'foot_r', 'foot_l', 'faceAttach']
    for bone_name in hide_bones:
        if bone := bones.get(bone_name):
            bone.hide = True

    bones.get('spine_01').use_inherit_rotation = False
    bones.get('neck_01').use_inherit_rotation = False

    # name, layer index
    # maps bone group to layer index
    bone_groups_to_layer_index = {
        'IKGroup': 1,
        'PoleGroup': 1,
        'TwistGroup': 2,
        'DynGroup': 3,
        'FaceGroup': 4,
        'ExtraGroup': 1
    }

    main_layer_bones = ['upperarm_r', 'lowerarm_r', 'upperarm_l', 'lowerarm_l', 'thigh_r', 'calf_r', 'thigh_l',
                         'calf_l', 'clavicle_r', 'clavicle_l', 'ball_r', 'ball_l', 'pelvis', 'spine_01',
                         'spine_02', 'spine_03', 'spine_04', 'spine_05', 'neck_01', 'neck_02', 'head', 'root']

    for bone in bones:
        if bone.name in main_layer_bones:
            bone.layers[1] = True
            continue

        if "eye" in bone.name.casefold():
            bone.layers[4] = True
            continue

        if group := pose_bones.get(bone.name).bone_group:
            if group.name in ['Unused bones', 'No children']:
                bone.layers[5] = True
                continue
            index = bone_groups_to_layer_index[group.name]
            bone.layers[index] = True


def constraint_object(child: bpy.types.Object, parent: bpy.types.Object, bone: str, rot=[radians(0), radians(90), radians(0)]):
    constraint = child.constraints.new('CHILD_OF')
    constraint.target = parent
    constraint.subtarget = bone
    child.rotation_mode = 'XYZ'
    child.rotation_euler = rot
    constraint.inverse_matrix = Matrix.Identity(4)

def mesh_from_armature(armature) -> bpy.types.Mesh:
    return armature.children[0]  # only used with psk, mesh is always first child

def armature_from_selection() -> bpy.types.Armature:
    armature_obj = None

    for obj in bpy.data.objects:
        if obj.type == 'ARMATURE' and obj.select_get():
            armature_obj = obj
            break

    if armature_obj is None:
        for obj in bpy.data.objects:
            if obj.type == 'MESH' and obj.select_get():
                for modifier in obj.modifiers:
                    if modifier.type == 'ARMATURE':
                        armature_obj = modifier.object
                        break

    return armature_obj

def append_data():
    addon_dir = os.path.dirname(os.path.splitext(__file__)[0])
    with bpy.data.libraries.load(os.path.join(addon_dir, "FortnitePortingData.blend")) as (data_from, data_to):
        for node_group in data_from.node_groups:
            if not bpy.data.node_groups.get(node_group):
                data_to.node_groups.append(node_group)

        for obj in data_from.objects:
            if not bpy.data.objects.get(obj):
                data_to.objects.append(obj)

def first(target, expr, default=None):
    if not target:
        return None
    filtered = filter(expr, target)

    return next(filtered, default)

def where(target, expr):
    if not target:
        return None
    filtered = filter(expr, target)

    return filtered

def any(target, expr):
    if not target:
        return None

    filtered = list(filter(expr, target))
    return len(filtered) > 0

def make_vector(data):
    return Vector((data.get("X"), data.get("Y"), data.get("Z")))

def import_response(response):
    append_data()
    global import_assets_root
    import_assets_root = response.get("AssetsRoot")

    global import_settings
    import_settings = response.get("Settings")
    
    global imported_materials
    imported_materials = {}

    import_datas = response.get("Data")
    
    for import_index, import_data in enumerate(import_datas):

        name = import_data.get("Name")
        import_type = import_data.get("Type")
    
        Log.information(f"Received Import for {import_type}: {name}")
        print(json.dumps(import_data))
    
        if import_type == "Dance":
            animation = import_data.get("Animation")
            props = import_data.get("Props")
            active_skeleton = armature_from_selection()
    
            if not import_anim(animation):
                message_box("An armature must be selected for the Emote to import onto.", "Failed to Import Emote", "ERROR")
                continue

            # remove face keyframes
            bpy.ops.object.mode_set(mode='POSE')
            bpy.ops.pose.select_all(action='DESELECT')
            pose_bones = active_skeleton.pose.bones
            bones = active_skeleton.data.bones
            if face_bone := first(bones, lambda x: x.name == "faceAttach"):
                face_bones = face_bone.children_recursive
                dispose_paths = []
                for bone in face_bones:
                    dispose_paths.append('pose.bones["{}"].rotation_quaternion'.format(bone.name))
                    dispose_paths.append('pose.bones["{}"].location'.format(bone.name))
                    dispose_paths.append('pose.bones["{}"].scale'.format(bone.name))
                    pose_bones[bone.name].matrix_basis = Matrix()
                dispose_curves = [fcurve for fcurve in active_skeleton.animation_data.action.fcurves if fcurve.data_path in dispose_paths]
                for fcurve in dispose_curves:
                    active_skeleton.animation_data.action.fcurves.remove(fcurve)
            bpy.ops.object.mode_set(mode='OBJECT')
            
            if len(props) == 0:
                continue

            existing_prop_skel = first(active_skeleton.children, lambda x: x.name == "Prop_Skeleton")
            if existing_prop_skel:
                bpy.data.objects.remove(existing_prop_skel, do_unlink=True)
    
            master_skeleton = import_skel(import_data.get("Skeleton"))
            master_skeleton.name = "Prop_Skeleton"
            master_skeleton.parent = active_skeleton
    
            bpy.context.view_layer.objects.active = master_skeleton
            import_anim(animation)
            master_skeleton.hide_set(True)
                      
            for propData in props:
                prop = propData.get("Prop")
                socket_name = propData.get("SocketName")
                socket_remaps = {
                    "RightHand": "weapon_r",
                    "LeftHand": "weapon_l",
                    "AttachSocket": "attach"
                }
    
                if socket_name in socket_remaps.keys():
                    socket_name = socket_remaps.get(socket_name)
    
                if (imported_item := import_mesh(prop.get("MeshPath"))) is None:
                        continue
    
                bpy.context.view_layer.objects.active = imported_item
    
                if animation := propData.get("Animation"):
                    import_anim(animation)
    
                imported_mesh = imported_item
                if imported_item.type == 'ARMATURE':
                    imported_mesh = mesh_from_armature(imported_item)
    
                for material in prop.get("Materials"):
                    index = material.get("SlotIndex")
                    import_material(imported_mesh.material_slots.values()[index], material)
    
                if location_offset := propData.get("LocationOffset"):
                    imported_item.location += make_vector(location_offset)*0.01
    
                if scale := propData.get("Scale"):
                    imported_item.scale = make_vector(scale)
    
                rotation = [0,0,0]
                if rotation_offset := propData.get("RotationOffset"):
                    rotation[0] += radians(rotation_offset.get("Roll"))
                    rotation[1] += radians(rotation_offset.get("Pitch"))
                    rotation[2] += -radians(rotation_offset.get("Yaw"))
                constraint_object(imported_item, master_skeleton, socket_name, rotation)
    
        else:
            imported_parts = []
            style_meshes = import_data.get("StyleMeshes")
            
            def import_parts(parts):
                for part in parts:
                    part_type = part.get("Part")
                    if any(imported_parts, lambda x: False if x is None else x.get("Part") == part_type) and import_type == "Outfit":
                        continue
    
                    target_mesh = part.get("MeshPath")
                    if found_mesh := first(style_meshes, lambda x: x.get("MeshToSwap") == target_mesh):
                        target_mesh = found_mesh.get("MeshToSwap")
                    
                    if (imported_part := import_mesh(target_mesh, reorient_bones=import_settings.get("ReorientBones"))) is None:
                        continue

                    imported_part.location += make_vector(part.get("Offset"))*0.01
                        
                    if import_type == "Prop":
                        imported_part.location = imported_part.location + Vector((1,0,0))*import_index
    
                    has_armature = imported_part.type == "ARMATURE"
                    if has_armature:
                        mesh = mesh_from_armature(imported_part)
                    else:
                        mesh = imported_part
                    bpy.context.view_layer.objects.active = mesh
    
                    imported_parts.append({
                        "Part": part_type,
                        "Armature": imported_part if has_armature else None,
                        "Mesh": mesh,
                        "Socket": part.get("SocketName")
                    })
                    
                    if (morph_name := part.get("MorphName")) and mesh.data.shape_keys is not None:
                        for key in mesh.data.shape_keys.key_blocks:
                            if key.name.casefold() == morph_name.casefold():
                                key.value = 1.0
    
                    if import_settings.get("QuadTopo"):
                        bpy.ops.object.editmode_toggle()
                        bpy.ops.mesh.tris_convert_to_quads(uvs=True)
                        bpy.ops.object.editmode_toggle()
    
                    for material in part.get("Materials"):
                        index = material.get("SlotIndex")
                        import_material(mesh.material_slots.values()[index], material)
    
                    for override_material in part.get("OverrideMaterials"):
                        index = override_material.get("SlotIndex")
                        import_material(mesh.material_slots.values()[index], override_material)
    
            import_parts(import_data.get("StyleParts"))
            import_parts(import_data.get("Parts"))
    
            for imported_part in imported_parts:
                mesh = imported_part.get("Mesh")
                for style_material in import_data.get("StyleMaterials"):
                    if slot := mesh.material_slots.get(style_material.get("MaterialNameToSwap")):
                        import_material(slot, style_material)
    
            if import_settings.get("MergeSkeletons") and import_type == "Outfit":
                master_skeleton = merge_skeletons(imported_parts)
                if RigType(import_settings.get("RigType")) == RigType.TASTY:
                    apply_tasty_rig(master_skeleton)
        
            bpy.ops.object.select_all(action='DESELECT')
    
def message_box(message = "", title = "Message Box", icon = 'INFO'):

    def draw(self, context):
        self.layout.label(text=message)

    bpy.context.window_manager.popup_menu(draw, title = title, icon = icon)

def register():
    import_event = threading.Event()

    global server
    server = Receiver(import_event)
    server.start()

    def handler():
        if import_event.is_set():
            try:
                import_response(server.data)
            except Exception as e:
                error_str = str(e)
                Log.error(f"An unhandled error occurred:")
                traceback.print_exc()
                message_box(error_str, "An unhandled error occurred", "ERROR")
                
            import_event.clear()
        return 0.01

    bpy.app.timers.register(handler, persistent=True)

def unregister():
    server.stop()
