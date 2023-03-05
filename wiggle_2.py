bl_info = {
    "name": "Wiggle 2",
    "author": "Steve Miller",
    "version": (2, 0, 0),
    "blender": (3, 00, 0),
    "location": "3d Viewport > Animation Panel",
    "description": "Simulate spring-like physics on Bone transforms",
    "warning": "",
    "wiki_url": "",
    "category": "Animation",
}

### TO DO #####

# Pinning
# Basic object jiggle?
# Implement a constant physics step
# Bounciness improve
# Mass improve


import bpy, math
from mathutils import Vector, Matrix, Euler, Quaternion, geometry
from bpy.app.handlers import persistent

#return m2 in m1 space
def relative_matrix(m1,m2):
    return (m2.inverted() @ m1).inverted()

def flatten(mat):
    dim = len(mat)
    return [mat[j][i] for i in range(dim) 
                      for j in range(dim)]
                      
def build_list():
    bpy.context.scene.wiggle.list.clear()
    for ob in bpy.context.scene.objects:
        if ob.type != 'ARMATURE': continue
        if not ob.wiggle_enable: continue
        wo = bpy.context.scene.wiggle.list.add()
        wo.name = ob.name
        ob.wiggle.list.clear()
        for b in ob.pose.bones:
            if not b.wiggle_enable: continue
            wb = ob.wiggle.list.add()
            wb.name = b.name
        
def update_prop(self,context,prop): 
    if type(self) == bpy.types.PoseBone: 
        for b in context.selected_pose_bones:
            b[prop] = self[prop]
    if prop == 'wiggle_enable':
        build_list()
        bpy.ops.wiggle.reset()
        
def get_parent(b):
    p = b.parent
    if not p: return None
    par = p if p.wiggle_enable else get_parent(p)
    return par

def length_world(b):
    return (b.id_data.matrix_world @ b.head - b.id_data.matrix_world @ b.tail).length

def collider_poll(self, object):
    return object.type == 'MESH'

def collide(b,dg):
    dt = bpy.context.scene.wiggle.dt
    
    pos = b.wiggle.position
    vel = b.wiggle.velocity
    cp = b.wiggle.collision_point
    co = b.wiggle.collision_ob
    radius = b.wiggle_radius
    sticky = b.wiggle_sticky
    bounce = b.wiggle_bounce
    friction = b.wiggle_friction
    
    colliders = []
    if b.wiggle_collider_type == 'Object' and b.wiggle_collider:
        colliders = [b.wiggle_collider]
    if b.wiggle_collider_type == 'Collection' and b.wiggle_collider_collection:
        colliders = [ob for ob in b.wiggle_collider_collection.objects if ob.type == 'MESH']
    col = False
    for collider in colliders:
        cmw = collider.matrix_world
        p = collider.closest_point_on_mesh(cmw.inverted() @ pos, depsgraph=dg)
        n = (cmw.to_quaternion().to_matrix().to_4x4() @ p[2]).normalized()
        i = cmw @ p[1]
        v = i-pos
        
        if (n.dot(v.normalized()) > 0.01) or (v.length < radius) or (co and (v.length < (radius+sticky))):
            if n.dot(v.normalized()) > 0: #vec is below
                nv = v.normalized()
            else: #normal is opposite dir to vec
                nv = -v.normalized()
            pos = i + nv*radius
            
            vel_bounce = vel.reflect(nv)
            v0 = pos + vel
            v1 = v0 + nv*5
            vec = geometry.intersect_line_plane(v0,v1,pos,nv)
            if vec:
                vel_slip = vec-pos
            else:
                print('bad data')
                vel_slip = Vector((0,0,0))
            vel = (vel_bounce*(bounce) + vel_slip*max(1-bounce,0))*(1-min(1,friction*60*dt))
            
            if co:
                collision_point = co.matrix_world @ cp
                pos = pos.lerp(collision_point, min(1,friction*60*dt))
            col = True
            co = collider
            cp = relative_matrix(cmw, Matrix.Translation(pos)).translation
    if not col:
        co = None
        cp = Vector((0,0,0))
        
    b.wiggle.position = pos
    b.wiggle.velocity = vel
    b.wiggle.collision_point = cp
    b.wiggle.collision_ob = co
    
def update_matrix(b):
    p = get_parent(b)
    if p:
        mat = p.wiggle.matrix @ relative_matrix(p.matrix, b.matrix) 
        mat3 = Matrix.LocRotScale(mat.decompose()[0], mat.decompose()[1],(b.id_data.matrix_world @ b.matrix).decompose()[2]) 
    else:
        mat = b.id_data.matrix_world @ b.matrix
        mat3 = mat
        
    tvec = relative_matrix(mat3, Matrix.Translation(b.wiggle.position)).translation
    rxz = tvec.to_track_quat('Y','Z')
    rot = rxz.to_matrix().to_4x4()
    
    if not p:
        sy = (b.id_data.matrix_world @ b.matrix.translation - b.wiggle.position).length/length_world(b)
    else:
        sy = (p.wiggle.matrix @ relative_matrix(p.matrix, b.matrix).translation - b.wiggle.position).length/length_world(b)
    scale = Matrix.Scale(sy,4,Vector((0,1,0)))

    if p:
        m4 = p.matrix @ relative_matrix(p.matrix, b.matrix)
        m5 = Matrix.LocRotScale(m4.decompose()[0], m4.decompose()[1],b.matrix.decompose()[2]) 
        b.matrix = m5 @ rot @ scale
    else:
        b.matrix = b.matrix @ rot @ scale
    b.wiggle.matrix = flatten(mat3 @ rot @ scale)

def wiggle(b,dg):
    mat = b.id_data.matrix_world @ b.matrix
    p = get_parent(b)
    if p:
        mat = p.wiggle.matrix @ relative_matrix(p.matrix, b.matrix)
        mat = Matrix.LocRotScale(mat.decompose()[0], mat.decompose()[1],b.matrix.decompose()[2])
            
    dt = bpy.context.scene.wiggle.dt
    if dt:
        multiplier = (bpy.context.scene.render.fps/60)
        #damp
        damp = max(min(1-b.wiggle_damp*dt, 1),0) 
        b.wiggle.position += b.wiggle.velocity*damp
    
        #gravity
        Fg = bpy.context.scene.gravity * b.wiggle_gravity
        b.wiggle.position += Fg*dt*dt
        
        #stiff animated 
        target = mat @ Vector((0,b.bone.length,0))
        target = mat.translation + (target - mat.translation).normalized()*b.bone.length
        s = target - b.wiggle.position #spring offset
        Fs = b.wiggle_stiff * s * multiplier #spring force
        b.wiggle.position += Fs*dt*dt
    update_matrix(b)

def stretch(b,i,dg):
    target = b.wiggle.matrix.translation + (b.wiggle.position - b.wiggle.matrix.translation).normalized()*length_world(b)
    s = (target - b.wiggle.position)*(1-b.wiggle_stretch)
    p = get_parent(b) 
    if p:
        if p == b.parent and i:
            if b.wiggle_mass==p.wiggle_mass:
                fac = 0.5
            else:
                fac = b.wiggle_mass/(p.wiggle_mass + b.wiggle_mass)
            p.wiggle.position -= s*fac
            b.wiggle.position += s*(1-fac)
        else:
            b.wiggle.position += s
        update_matrix(p)
    else:
        b.wiggle.position += s
    collide(b,dg)
    update_matrix(b)
        
@persistent
def wiggle_pre(scene):
    if not scene.wiggle_enable: return
    for wo in scene.wiggle.list:
        if wo.name not in scene.objects:
            build_list()
            return
        ob = scene.objects[wo.name]
        for wb in ob.wiggle.list:
            if wb.name not in ob.pose.bones:
                build_list()
                return
            b = ob.pose.bones[wb.name]

            b.location = Vector((0,0,0))
            b.rotation_quaternion = Quaternion((1,0,0,0))
            b.rotation_euler = Vector((0,0,0))
            b.scale = Vector((1,1,1))
    bpy.context.view_layer.update()

@persistent                
def wiggle_post(scene,dg):
    if not scene.wiggle_enable: return

    lastframe = scene.wiggle.lastframe
    if (scene.frame_current == scene.frame_start) and (scene.wiggle.loop == False):
        bpy.ops.wiggle.reset()
    if scene.frame_current >= lastframe:
        frames_elapsed = scene.frame_current - lastframe
    else:
        e1 = (scene.frame_end - lastframe) + (scene.frame_current - scene.frame_start) + 1
        e2 = lastframe - scene.frame_current
        frames_elapsed = min(e1,e2)
    if frames_elapsed > 4: frames_elapsed = 1 #handle large jumps?
    scene.wiggle.dt = 1/scene.render.fps * frames_elapsed
    scene.wiggle.lastframe = scene.frame_current
    
    for wo in scene.wiggle.list:
        ob = scene.objects[wo.name]
        bones = []
        for wb in ob.wiggle.list:
            bones.append(ob.pose.bones[wb.name])
        for b in bones:
            wiggle(b,dg)
        for i in range(scene.wiggle.iterations):
            for b in bones:
                stretch(b, scene.wiggle.iterations-1-i,dg)
        if frames_elapsed:
            for b in bones:
                b.wiggle.velocity = (b.wiggle.position - b.wiggle.position_last)/max(frames_elapsed,1)
                b.wiggle.position_last = b.wiggle.position
            
class WiggleCopy(bpy.types.Operator):
    """Copy active wiggle settings to selected bones"""
    bl_idname = "wiggle.copy"
    bl_label = "Copy Settings"
    
    @classmethod
    def poll(cls,context):
        return context.mode in ['POSE'] and context.active_pose_bone
    
    def execute(self,context):
        b = context.active_pose_bone
        b.wiggle_enable = b.wiggle_enable
        b.wiggle_mass = b.wiggle_mass
        b.wiggle_stiff = b.wiggle_stiff
        b.wiggle_stretch = b.wiggle_stretch
        b.wiggle_damp = b.wiggle_damp
        b.wiggle_gravity = b.wiggle_gravity
        b.wiggle_radius = b.wiggle_radius
        b.wiggle_friction = b.wiggle_friction
        b.wiggle_bounce = b.wiggle_bounce
        b.wiggle_sticky = b.wiggle_sticky
        return {'FINISHED'}

class WiggleReset(bpy.types.Operator):
    """Reset wiggle physics to rest state"""
    bl_idname = "wiggle.reset"
    bl_label = "Reset State"
    
    @classmethod
    def poll(cls,context):
        return context.mode in ['OBJECT', 'POSE']
    
    def execute(self,context):
        wiggle_pre(bpy.context.scene)
        for wo in context.scene.wiggle.list:
            ob = context.scene.objects[wo.name]
            for wb in ob.wiggle.list:
                b = ob.pose.bones[wb.name]
                rest_mat = b.id_data.matrix_world @ b.bone.matrix_local
                if b.parent:
                    rest_mat = b.id_data.matrix_world @ b.parent.matrix @ relative_matrix(b.parent.bone.matrix_local, b.bone.matrix_local)
                b.wiggle.position = b.wiggle.position_last = rest_mat @ Vector((0,b.bone.length,0))
                b.wiggle.velocity = Vector((0,0,0))
                b.wiggle.matrix = flatten(rest_mat)
                context.scene.wiggle.lastframe = context.scene.frame_current
        return {'FINISHED'}
    
class WIGGLE_PT_Settings(bpy.types.Panel):
    bl_category = 'Animation'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_label = 'Wiggle 2'
    
    @classmethod
    def poll(cls, context):
        return context.active_object
    
    def draw(self,context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        def drawprops(layout,b,props):
            for p in props:
                layout.prop(b, p)
        def active_panel(layout):
            row = layout.row()
            row.prop(context.scene, 'wiggle_enable', icon = 'SCENE_DATA',icon_only=True)
            ob = context.object
            if ob.type == 'ARMATURE':
                row.prop(ob, 'wiggle_enable', icon = 'OBJECT_DATA',icon_only=True)
            if not context.scene.wiggle_enable or context.active_object.mode != 'POSE' or not context.active_pose_bone:
                return
            b = context.active_pose_bone
            row.prop(b, 'wiggle_enable', icon = 'BONE_DATA',icon_only=True)
            if not b.wiggle_enable:
                return
            drawprops(layout,b,['wiggle_mass','wiggle_stiff','wiggle_stretch','wiggle_damp','wiggle_gravity'])
            layout.separator()
            layout.prop(b, 'wiggle_collider_type',text='Collisions')
            if b.wiggle_collider_type == 'Object':
                layout.prop_search(b, 'wiggle_collider', context.scene, 'objects',text=' ')
            else:
                layout.prop_search(b, 'wiggle_collider_collection', context.scene.collection, 'children', text=' ')
            drawprops(layout,b,['wiggle_radius','wiggle_friction','wiggle_bounce','wiggle_sticky'])
            layout.separator()
            layout.operator('wiggle.copy')
        active_panel(layout)
        layout.separator()
        layout.label(text='Global Settings')
        layout.prop(context.scene.wiggle, 'iterations')
        layout.prop(context.scene.wiggle, 'loop')
        layout.operator('wiggle.reset')
        
class WiggleItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()        

#store properties for a bone. custom properties for user editable. property group for internal calculations
class WiggleBone(bpy.types.PropertyGroup):
    matrix: bpy.props.FloatVectorProperty(name = 'Matrix', size=16, subtype = 'MATRIX')
    position: bpy.props.FloatVectorProperty(subtype='TRANSLATION')
    position_last: bpy.props.FloatVectorProperty(subtype='TRANSLATION')
    velocity: bpy.props.FloatVectorProperty(subtype='VELOCITY')
    
    collision_point:bpy.props.FloatVectorProperty(subtype = 'TRANSLATION')
    collision_ob: bpy.props.PointerProperty(type=bpy.types.Object)
    
class WiggleObject(bpy.types.PropertyGroup):
    list: bpy.props.CollectionProperty(type=WiggleItem)
    
class WiggleScene(bpy.types.PropertyGroup):
    dt: bpy.props.FloatProperty()
    lastframe: bpy.props.IntProperty()
    iterations: bpy.props.IntProperty(name='Quality', description='Increase solver iterations for better chain physics', min=1, default=1, max=4)
    loop: bpy.props.BoolProperty(name='Looping', description='Physics continues as timeline loops', default=True)
    list: bpy.props.CollectionProperty(type=WiggleItem)

def register():
    #user variables
    bpy.types.Scene.wiggle_enable = bpy.props.BoolProperty(
        name = 'Enable',
        description = 'Enable jiggle on this scene',
        default = False,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_enable')
    )
    bpy.types.Object.wiggle_enable = bpy.props.BoolProperty(
        name = 'Enable',
        description = 'Enable jiggle on this object',
        default = False,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_enable')
    )
    bpy.types.PoseBone.wiggle_enable = bpy.props.BoolProperty(
        name = 'Enable',
        description = 'Enable jiggle on this bone',
        default = False,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_enable')
    )
    bpy.types.PoseBone.wiggle_mass = bpy.props.FloatProperty(
        name = 'Mass',
        description = 'Mass of bone (kinda not totally implemented)',
        min = 0.01,
        default = 1,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_mass')
    )
    bpy.types.PoseBone.wiggle_stiff = bpy.props.FloatProperty(
        name = 'Stiff',
        description = 'Stiffness coefficient, can be large numbers',
        min = 0,
        default = 20,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_stiff')
    )
    bpy.types.PoseBone.wiggle_stretch = bpy.props.FloatProperty(
        name = 'Stretch',
        description = 'Stretch factor, 0 to 1 range',
        min = 0,
        default = 0,
        max=1,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_stretch')
    )
    bpy.types.PoseBone.wiggle_damp = bpy.props.FloatProperty(
        name = 'Damp',
        description = 'Dampening coefficient, can be greater than 1',
        min = 0,
        default = 1,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_damp')
    )
    bpy.types.PoseBone.wiggle_gravity = bpy.props.FloatProperty(
        name = 'Gravity',
        description = 'Multiplier for scene gravity',
        default = 1,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_gravity')
    )
    bpy.types.PoseBone.wiggle_collider_type = bpy.props.EnumProperty(
        name='Collider Type',
        items=[('Object','Object','Collide with a selected mesh'),('Collection','Collection','Collide with all meshes in selected collection')],
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_collider_type')
    )
    bpy.types.PoseBone.wiggle_collider = bpy.props.PointerProperty(
        name='Collider Object', 
        description='Mesh object to collide with', 
        type=bpy.types.Object, 
        poll = collider_poll, 
        override={'LIBRARY_OVERRIDABLE'}, 
        update=lambda s, c: update_prop(s, c, 'wiggle_collider')
    )
    bpy.types.PoseBone.wiggle_collider_collection = bpy.props.PointerProperty(
        name = 'Collider Collection', 
        description='Collection to collide with', 
        type=bpy.types.Collection, 
        override={'LIBRARY_OVERRIDABLE'}, 
        update=lambda s, c: update_prop(s, c, 'wiggle_collider_collection')
    )
    
    bpy.types.PoseBone.wiggle_radius = bpy.props.FloatProperty(
        name = 'Radius',
        description = 'Collision radius',
        min = 0,
        default = 0,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_radius')
    )
    bpy.types.PoseBone.wiggle_friction = bpy.props.FloatProperty(
        name = 'Friction',
        description = 'Friction when colliding',
        min = 0,
        default = 0.5,
        soft_max = 1,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_friction')
    )
    bpy.types.PoseBone.wiggle_bounce = bpy.props.FloatProperty(
        name = 'Bounce',
        description = 'Bounciness when colliding',
        min = 0,
        default = 0.5,
        soft_max = 1,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_bounce')
    )
    bpy.types.PoseBone.wiggle_sticky = bpy.props.FloatProperty(
        name = 'Sticky',
        description = 'Stickiness when colliding (small numbers often suffice)',
        min = 0,
        default = 0,
        soft_max = 1,
        override={'LIBRARY_OVERRIDABLE'},
        update=lambda s, c: update_prop(s, c, 'wiggle_sticky')
    )
    
    #internal variables
    bpy.utils.register_class(WiggleItem)
    bpy.utils.register_class(WiggleBone)
    bpy.types.PoseBone.wiggle = bpy.props.PointerProperty(type=WiggleBone, override={'LIBRARY_OVERRIDABLE'})
    bpy.utils.register_class(WiggleObject)
    bpy.types.Object.wiggle = bpy.props.PointerProperty(type=WiggleObject, override={'LIBRARY_OVERRIDABLE'})
    bpy.utils.register_class(WiggleScene)
    bpy.types.Scene.wiggle = bpy.props.PointerProperty(type=WiggleScene, override={'LIBRARY_OVERRIDABLE'})
    
    bpy.utils.register_class(WiggleReset)
    bpy.utils.register_class(WiggleCopy)
    bpy.utils.register_class(WIGGLE_PT_Settings)
    
#    bpy.app.handlers.frame_change_pre.clear()
#    bpy.app.handlers.frame_change_post.clear()
#    bpy.app.handlers.render_pre.clear()
#    bpy.app.handlers.render_post.clear()
    
    bpy.app.handlers.frame_change_pre.append(wiggle_pre)
    bpy.app.handlers.frame_change_post.append(wiggle_post)

def unregister():
    bpy.utils.unregister_class(WiggleItem)
    bpy.utils.unregister_class(WiggleBone)
    bpy.utils.unregister_class(WiggleObject)
    bpy.utils.unregister_class(WiggleScene)
    bpy.utils.unregister_class(WiggleReset)
    bpy.utils.unregister_class(WiggleCopy)
    bpy.utils.unregister_class(WIGGLE_PT_Settings)
    
    bpy.app.handlers.frame_change_pre.remove(wiggle_pre)
    bpy.app.handlers.frame_change_post.remove(wiggle_post)
    
if __name__ == "__main__":
    register()
